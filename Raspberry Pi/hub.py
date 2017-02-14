import time
from pubnub import Pubnub 
import pubnub_meta as PubnubMeta
from RF24 import *
import RPi.GPIO as GPIO
import rf_util as RFUtil
from my_class import *

#################################
###### VARIABLE DEFINITION ######
#################################

# Hub definition
HUB_NAME = "Hub 1"
HUB_ADDRESS = 0xFA00

# Devices dictionary [Device name] : [Device address]
DEVICES_DICTIONARY = BiDict({
    "Device 1":0xFA01,
    "Device 2":0xFA02
    })

# Parking lot object dictionary [Sensor name] : [Parking lot obj]
PARKING_LOT_DICTIONARY = {
    "Device 1":ParkingLot(0xFA01,0xAA01,0xBB01,0xCC01)
    }

# Wait for ACK payload
global WAIT_FOR_ACK
WAIT_FOR_ACK = False

# Global statuc checker
global POLLING_STATUS
global REQUEST_STATUS
POLLING_STATUS = False
REQUEST_STATUS = False

###################################
###### LIBRARY CONFIGURATION ######     
###################################

# Initialize Pubnub API
pubnub = Pubnub(publish_key = PubnubMeta.PUBLISH_KEY,
                subscribe_key = PubnubMeta.SUBSCRIBE_KEY)

# Setup nRF24L01 radio with SPIDEV, GPIO 22 and CE0 CSN
# In general, use RF24(<ce_pin>, <a>*10+<b>)
# for proper SPIDEV constructor to address correct
# spi device at /dev/spidev<a>.<b>
radio = RF24(22,0)

###################################
####### FUNCTION DEFINITION #######
###################################

# Basic function to calculate time in milliseconds
millis = lambda: int(round(time.time() * 1000))

####### PubNub API callback #######
def _pubnub_callback(json, channel):
    message = PubnubMeta.get_message(HUB_NAME, json)
    print(message)
    if message != None:
        _execute_message(message)
    
def _pubnub_error(json):
    print(json)

def _pubnub_connect(channel):
    print(PubnubMeta.MESSAGE_CONNECT.format(channel))

def _pubnub_reconnect(channel):
    print(PubnubMeta.MESSAGE_RECONNECT.format(channel))

def _pubnub_disconnect(channel):
    print(PubnubMeta.MESSAGE_DISCONNECT.format(channel))

####### RF functions #######
def _execute_message(message):
    global REQUEST_STATUS
    global POLLING_STATUS
    REQUEST_STATUS = True
    while POLLING_STATUS:
        time.sleep(0.1)
    if message.command == RFUtil.CMD_TEST:
        _send_payload_process(message)
        time.sleep(10)
    REQUEST_STATUS = False

def _send_payload_process(message):
    payload = RFUtil.generate_payload(DEVICES_DICTIONARY, message)
    if payload != None:
        ack = False
        resendTime = 0
        while not ack and resendTime < RFUtil.MAX_RESEND_PAYLOAD:
            _send_payload(payload)
            ack = _wait_ack_payload(message)
            resendTime = resendTime + 1

def _send_payload(payload):
    if payload != None:
        radio.stopListening()
        print("Now sending ... ", end="")
        RFUtil.print_payload(payload)
        radio.write(payload)

def _send_ack_payload(target_address):
    payload = RFUtil.generate_ack_payload(target_address)
    if payload != None:
        radio.stopListening()
        print("Now sending ... ", end="")
        RFUtil.print_payload(payload)
        radio.write(payload)
        radio.startListening()

def _wait_ack_payload(message):
    radio.startListening()
    started_waiting_at = millis()
    timeout = False
    resend = False
    while not timeout:
        if radio.available():
            len = radio.getDynamicPayloadSize()
            receive_payload = radio.read(len)
            print("Get response ... ", end="")
            RFUtil.print_payload(receive_payload)
            device_address = RFUtil.get_payload_address(receive_payload)
            if device_address == DEVICES_DICTIONARY[message.target]:
                if receive_payload[2] != RFUtil.get_command_address(RFUtil.CMD_ACK):
                    resend = True
                else:
                    return True
        if (millis() - started_waiting_at) > RFUtil.MAX_WAITING_MILLIS:
            timeout = True
    if timeout or resend:
        return False

def _process_payload(payload, target_address):
    print("Start process payload")
    # Payload error detecting
    if RFUtil.is_validated(payload):
        print("Checksum OK")
        # Check the device address of payload
        device_address = RFUtil.get_payload_address(payload)
        if device_address == target_address:
            print("Target OK")
            # First, send ACK payload
            _send_ack_payload(device_address)
            return True
    return False

#############################
####### MAIN PROGRAM ########
#############################

# Start radio
radio.begin()
radio.enableDynamicPayloads()
radio.setRetries(5,15)
radio.printDetails()
radio.openWritingPipe(RFUtil.PIPES[0])
radio.openReadingPipe(1,RFUtil.PIPES[1])
radio.startListening()

# Start Pubnub
try:
    pubnub.subscribe(channels = PubnubMeta.CHANNEL_DEBUG,
                     callback = _pubnub_callback,
                     error = _pubnub_error,
                     connect = _pubnub_connect,
                     reconnect = _pubnub_reconnect,
                     disconnect = _pubnub_disconnect)
    while True:
        while REQUEST_STATUS:
            POLLING_STATUS = False
            time.sleep(0.1)
        POLLING_STATUS = True
        print("Start polling")
        for sensor_address, lot in PARKING_LOT_DICTIONARY.items():
            message = PubnubMessage(RFUtil.CMD_LOT_STATUS, sensor_address, None)
            _send_payload_process(message)
            
            started_waiting_at = millis()
            total_waiting_time = RFUtil.MAX_WAITING_MILLIS * RFUtil.MAX_RESEND_PAYLOAD
            while (millis() - started_waiting_at) < total_waiting_time:
                if radio.available():
                    len = radio.getDynamicPayloadSize()
                    receive_payload = radio.read(len)
                    print("Get payload ... ", end="")
                    RFUtil.print_payload(receive_payload)
                    check_payload = _process_payload(receive_payload, lot.sensor_address)
                    if check_payload:
                        break
        print("End polling")
        time.sleep(0.1)
finally:
    print("Pubnub stop")
    pubnub.stop()
    print("GPIO cleanup")
    GPIO.cleanup()
