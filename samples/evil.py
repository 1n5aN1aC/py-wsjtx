import time
import os
import sys
import copy
import pickle
import re
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pywsjtx.extra.simple_server
from pathlib import Path

#########################
###        Tips       ###
#########################

#
#
#
#
#
#In WSJTX, set the unattended timeout to the minimum. (1 minute)
#	This will not impact number of contacts, as the script will trigger a "human" response every cycle when it chooses who to respond to.
#	But if something went wrong, this will prevent continuously respond to the same person for too long.  :)


#########################
###   Configuration   ###
#########################

#IP_ADDRESS = '224.1.1.1'
#PORT = 5007

IP_ADDRESS = '127.0.0.1'
PORT = 2238

SAVE_LOCATION = "seen.pickle"

MY_CALL = "K1MI"

#Values used to update running point tallies
VALUE_FOR_NEW_CALLS         =    100 #Points a call starts with when first decoded
VALUE_ADDED_PER_HEAR        =      1 #Points added each time we decode someone
VALUE_REMOVED_PER_CALL      =    -20 #Points removed each time we respond to someone

#Values used only to decide which call to respond to
VALUE_OF_CQ                 =  -1000 #How should we prioritize calling CQ?             (TODO)
VALUE_EXTRA_FOR_DIRECT_CALL =  10000 #Prioritize returning calls directed at us
VALUE_EXTRA_FOR_NEW_CALL    =   1000 #Bonus prioritization for calls we've only seen a few times
VALUE_EXTRA_FOR_REPEAT_CALL = -10000 #De-Prioritize calls we already logged a contact with
VALUE_EXTRA_FOR_CQ          =     50 #Prioritize CQ calls (over RR73/73)

#Values used specifically for when someone mentions our callign
VALUE_DIRECTED_TX1_EXTRA    =     10 #CM84 Extra value added
VALUE_DIRECTED_TX1_BACKOFF  =     -1 #CM84 Backoff from running points
VALUE_DIRECTED_TX2_EXTRA    =     50 # +12 Extra value added
VALUE_DIRECTED_TX2_BACKOFF  =    -20 # +12 Backoff from running points 
VALUE_DIRECTED_TX3_EXTRA    =    100 #R-02 Extra value added
VALUE_DIRECTED_TX3_BACKOFF  =    -30 #R-02 Backoff from running points
VALUE_DIRECTED_TX4_EXTRA    =    300 #RR73 Extra value added
VALUE_DIRECTED_TX4_BACKOFF  =    -80 #RR73 Backoff from running points
VALUE_DIRECTED_TX5_EXTRA    = -10000 #  73 (No need to respond to calling 73 at us)
VALUE_DIRECTED_TX5_BACKOFF  =    -10 #  73 (No need to respond to calling 73 at us)


#########################
###   Program Setup   ###
#########################

#Global variables
s = pywsjtx.extra.simple_server.SimpleServer(IP_ADDRESS, PORT, timeout=2.0)
db = {}
recent_calls = {}
previous_decode_mode = 0

#If we have an existing db, we load it.
try:
	with open(SAVE_LOCATION, 'r+b') as f:
		db = pickle.load(f)
		print("Loaded existing DB.")
except:
	print("No DB!  Creating new database!")
	with open(SAVE_LOCATION, 'wb') as f:
		pickle.dump(db, f, pickle.HIGHEST_PROTOCOL)


#########################
###     Functions     ###
#########################

#Extract information from the packet
#Returns:  packet_type, caller, callee, special_decode_mode
def decode_packet(the_packet):
	split = the_packet.message.split()
	#CQ
	if len(split) > 1 and split[0] == "CQ":
		packet_type = "CQ"
		caller = split[1]
		callee = None
	#RR73
	elif len(split) > 2 and (split[2] == "RR73" or split[2] == "RRR"):
		packet_type = "RR73"
		caller = split[1]
		callee = split[0]
	#73
	elif len(split) > 2 and split[2] == "73":
		packet_type = "73"
		caller = split[1]
		callee = split[0]
	#Call
	elif len(split) > 2 and re.search("[A-Z]{2}[0-9]{2}", split[2]):
		packet_type = "Call"
		caller = split[1]
		callee = split[0]
	#Report
	elif len(split) > 2 and re.search("[+-][0-9]{2}", split[2]):
		packet_type = "+00"
		caller = split[1]
		callee = split[0]
	#Response Report
	elif len(split) > 2 and re.search("R[+-][0-9]{2}", split[2]):
		packet_type = "R+00"
		caller = split[1]
		callee = split[0]
	#Unknown
	else:
		print ("unable to decode packet:")
		print (the_packet)
		return None, None, None, None
	#Check if there is any special aP mode used
	if re.search("a[0-9]{1}", split[-1]):
		special_decode_mode = split[-1]
	else:
		special_decode_mode = None
	#Return the decoded information
	return packet_type, caller, callee, special_decode_mode

#Process a new received message
def process_packet(the_packet, packet_type, caller, callee, special_decode_mode):
	if special_decode_mode:
		#print ("TODO:  Special decode mode")
		return
	add_to_db(the_packet, caller)
	#Only add to recent if it is reply-able.  (CQ,73, or directed to me)
	if (callee == MY_CALL) or (packet_type == "CQ") or (packet_type == "RR73") or (packet_type == "73"):
		add_to_recent(the_packet, caller)
		decide_value(the_packet, caller, callee, packet_type, special_decode_mode)
		print(db[caller]["message_last"].message + ", " + str(db[caller]["points"]) + "/" + str(recent_calls[caller]["points"]) + ", " + str(recent_calls[caller]["QSL"]))

#Update the DB with data from the received packet
def add_to_db(the_packet, call):
	#If it's a user we haven't heard before:
	if call not in db:
		db[call] = {}
		db[call]["call"] = call
		db[call]["message_last"] = the_packet
		db[call]["message_time"] = the_packet.time
		db[call]["QSL"]    = False
		db[call]["points"] = VALUE_FOR_NEW_CALLS
		db[call]["heard"]  = 1
	else:
		db[call]["message_last"] = the_packet
		db[call]["message_time"] = the_packet.time
		db[call]["points"] += VALUE_ADDED_PER_HEAR
		db[call]["heard"]  += 1

#Also update the recent packet list
def add_to_recent(the_packet, call):
	recent_calls[call] = copy.deepcopy(db[call])

#Decide the value of a received packet (for recent packets list)
def decide_value(the_packet, call, callee, packet_type, special_decode_mode):
	#Modifier for having already made contact with the person:
	if db[call]["QSL"] == True:
		decide_value_repeat(the_packet, call, packet_type)
	#Modifier for if my call is in the packet:
	if callee == MY_CALL:
		decide_value_own(the_packet, call, packet_type)
		return
	#Modifier for RR73
	if packet_type == "CQ":
		recent_calls[call]["points"] += VALUE_EXTRA_FOR_CQ
	#Modifier for extra new calls
	if db[call]["heard"] < 10:
		recent_calls[call]["points"] += VALUE_EXTRA_FOR_NEW_CALL

#Special points handling for packets with our call in it:
def decide_value_own(the_packet, call, packet_type):
	recent_calls[call]["points"] += VALUE_EXTRA_FOR_DIRECT_CALL
	#Do not reply to someone responding to us with 73
	if packet_type == "73":
		recent_calls[call]["points"] += VALUE_DIRECTED_TX5_EXTRA
		db[call]["points"]           += VALUE_DIRECTED_TX5_BACKOFF
	#Priority 1 is responding to someone responding to us with RR73
	elif packet_type == "RR73":
		recent_calls[call]["points"] += VALUE_DIRECTED_TX4_EXTRA
		db[call]["points"]           += VALUE_DIRECTED_TX4_BACKOFF
	#Priority 2 is responding to someone responding to us with our signal report
	elif packet_type == "R+00":
		recent_calls[call]["points"] += VALUE_DIRECTED_TX3_EXTRA
		db[call]["points"]           += VALUE_DIRECTED_TX3_BACKOFF
	#Priority 3 is responding to someone responding to us with our signal report
	elif packet_type == "+00":
		recent_calls[call]["points"] += VALUE_DIRECTED_TX2_EXTRA
		db[call]["points"]           += VALUE_DIRECTED_TX2_BACKOFF
	#Priority 4 is responding to someone calling us
	elif packet_type == "Call":
		recent_calls[call]["points"] += VALUE_DIRECTED_TX1_EXTRA
		db[call]["points"]           += VALUE_DIRECTED_TX1_BACKOFF

#Special points handling for those we have already made contact with:
def decide_value_repeat(the_packet, call, packet_type):
	#Special case for getting RR73's.  We may have logged them, but they may not have logged us.
	#So we give both a good amount of bonus points to this case, but also quite a bit of backoff to prevent abuse
	if packet_type == "RR73":
		recent_calls[call]["points"] += 1000
		db[call]["points"]           += -300
	else:
		recent_calls[call]["points"] += VALUE_EXTRA_FOR_REPEAT_CALL

#########################
###    Main Logic     ###
#########################

#Handles status packets
def handle_status_packet(the_packet):
	global previous_decode_mode
	
	#We only process if the decoding mode has changed...
	if not the_packet.decoding == previous_decode_mode:
		previous_decode_mode = the_packet.decoding
		#WSJT-X sends us multiple decoding cycles.  We act on each of them, but only if the best has changed
		if the_packet.decoding == 0 and len(recent_calls) > 0:
			#Decide who to call
			winner = max(recent_calls.values(), key=lambda x: int(x['points']))
			#Were we already calling the best call?
			if the_packet.dx_call == winner["call"]:
				#print ("already responding to optimal call.")
				pass
			else:
				print("Replying to: " + winner["message_last"].message)
				reply_pkt = pywsjtx.ReplyPacket.Builder(winner["message_last"])
				s.send_packet(addr_port, reply_pkt)
		
			#If this is the last status packet before a new cycle, we also clear the recent calls list:
			seconds = time.time()%60
			if ((seconds > 15 and seconds < 16)
			 or (seconds > 30 and seconds < 31)
			 or (seconds > 45 and seconds < 46)
			 or (seconds >  0 and seconds <  1)):
				#But we need to clean up even if we don't change the active call
				recent_calls.clear()
				db[winner["call"]]["points"] += VALUE_REMOVED_PER_CALL

#Main loop
while True:
	#receive packet
	(pkt, addr_port) = s.rx_packet()
	if (pkt != None):
		the_packet = pywsjtx.WSJTXPacketClassFactory.from_udp_packet(addr_port, pkt)
		#Save on Heartbeats
		if type(the_packet) == pywsjtx.HeartBeatPacket:
			with open(SAVE_LOCATION, 'wb') as f:
				pickle.dump(db, f, pickle.HIGHEST_PROTOCOL)
		#Use status packets to decide who to call next
		elif type(the_packet) == pywsjtx.StatusPacket:
			#print("------------Decoding:" + str(the_packet.decoding) + " tx_enabled: " + str(the_packet.tx_enabled))
			#print(the_packet)
			handle_status_packet(the_packet)
		#Store Decodes in the DB
		elif type(the_packet) == pywsjtx.DecodePacket:
			packet_type, caller, callee, special_decode_mode = decode_packet(the_packet)
			process_packet(the_packet, packet_type, caller, callee, special_decode_mode)
		#Handle QSL packet
		elif type(the_packet) == pywsjtx.QSOLoggedPacket:
			#This means we need to log this callsign as having completed a contact
			print("Logged sucessfull QSO with: " + the_packet.call)
			db[the_packet.call]["QSL"] = True
		#Unknown packets...
		else:
			print(the_packet)
