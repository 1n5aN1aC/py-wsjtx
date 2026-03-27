import os
import sys
import pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pywsjtx.extra.simple_server
from pathlib import Path

#IP_ADDRESS = '224.1.1.1'
#PORT = 5007

IP_ADDRESS = '127.0.0.1'
PORT = 2238

SAVE_LOCATION = "seen.pickle"

s = pywsjtx.extra.simple_server.SimpleServer(IP_ADDRESS, PORT, timeout=2.0)
db = {}
recent_calls = {}

#If we have an existing db, we load it.
try:
	with open(SAVE_LOCATION, 'r+b') as f:
		db = pickle.load(f)
		print("Loaded existing DB.")
except:
	print("No DB!  Creating new database!")
	pickle.dump(db, f, pickle.HIGHEST_PROTOCOL)

#Process a new received message
def process_packet(the_packet):
	#Extract the calling station's call
	split = the_packet.message.split()
	call = split[-2]
	#Now process the packet
	add_to_db(the_packet, call)
	add_to_recent(the_packet, call)

#Update the DB with data from the received packet
def add_to_db(the_packet, call):
	#If it's a user we haven't heard before:
	if call not in db:
		db[call] = {}
		db[call]["call"] = call
		db[call]["message_last"] = the_packet
		db[call]["message_time"] = the_packet.time
		db[call]["QSL"] = False
		db[call]["points"] = 100
		#print("added new: " + call + " (#" + str(len(db)) + ")")
	else:
		db[call]["message_last"] = the_packet
		db[call]["message_time"] = the_packet.time
		db[call]["points"] += 1
		#print(call + "- " + str(db[call]["points"]))
	#Add this recent packet to the recent packets list
	add_to_recent(the_packet, call)

#Also update the recent packet list
def add_to_recent(the_packet, call):
	recent_calls[call] = db[call]
	decide_value(the_packet, call)
	print(db[call]["message_last"].message + ", " + str(recent_calls[call]["points"]))
	

#Decide the value of a received packet (for recent packets list)
def decide_value(the_packet, call):
	#If my call is in the packet:
	if "K1MI" in db[call]["message_last"].message:
		#if the_packet.message.split()[-1] is not "73":
		recent_calls[call]["points"] += 10000
	#If we have already made contact with the person:
	if db[call]["QSL"] == True:
		recent_calls[call]["points"] -= 10000

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
			if the_packet.decoding == 0:
				if the_packet.transmitting == 0:
					if len(recent_calls) > 0:
						winner = max(recent_calls.values(), key=lambda x: int(x['points']))
						print("Replying to: " + winner["message_last"].message)
						reply_pkt = pywsjtx.ReplyPacket.Builder(winner["message_last"])
						#s.send_packet(addr_port, reply_pkt)
						recent_calls = {}
						db[winner["call"]]["points"] -= 50
		#Store Decodes in the DB
		elif type(the_packet) == pywsjtx.DecodePacket:
			#If the message starts with CQ, process it
			if the_packet.message.startswith("CQ"):
				process_packet(the_packet)
			#If the message ends with RR (covers the RR73 Case too)
			elif the_packet.message.endswith("73"):
				process_packet(the_packet)

			#	print(the_packet.message)
			#	reply_pkt = pywsjtx.ReplyPacket.Builder(the_packet)
			#	s.send_packet(addr_port, reply_pkt)
		else:
			print(the_packet)
