import datetime
from socket import *
import pickle
import sys
import argparse
import threading
import time
import random

# The player node class
class Player:
    def __init__(self, host="", port=65432):
        self.host = ""
        self.port = random.randint(49152, 65534) # Pick a random port between 49152 and 65534
        self.bingo_host = host
        self.bingo_host_port = port
        self.socket = socket(AF_INET, SOCK_STREAM)
        self.server_socket = socket(AF_INET, SOCK_STREAM)
        self.peer_sockets = []
        self.players = []
        self.connections = []
        self.drawn_numbers = []
        self.bingo_card = []
        self.game_over = False
        print("What's your name?")
        self.name = input()
        self.player = {
            "address": "", 
            "client_port": "", 
            "server_port": self.port, 
            "name": self.name
        }
        self.launch()

    def launch(self):
        # Connect to the host
        print("Connecting to host: ", self.bingo_host, self.bingo_host_port)
        self.socket.connect((self.bingo_host, self.bingo_host_port))
        # Register with the host
        self.register()
        while not self.game_over:
            data = self.socket.recv(1024)
            data = pickle.loads(data)
            # Message from the host that the player has been accepted
            if data["type"] == "accept_player":
                self.handle_registration_accepted(data)
            # Message from the host that the game is starting
            elif data["type"] == "start_message":
                self.handle_game_start(data)
            # Message from the host that a new number has been drawn
            elif data["type"] == "bingo_number":
                self.handle_bingo_number(data)
            # Message from the host to check the consensus on a bingo
            elif data["type"] == "consensus_round":
                self.handle_consensus_round(data)
            # Message from the host that a player has been removed from the game
            elif data["type"] == "remove_player":
                self.handle_remove_player(data)
            # Message from the host that the game is over
            elif data["type"] == "end_message":
                self.handle_end_message(data)
                break                
            # else if there is content field in data, print content
            elif "content" in data:
                print(data["content"])
            else:
                print("Unknown message type: ", data["type"])
            # todo at least:
            # handle card hit message to other players
            # handle sync request to other players
            # handle sync response from other players

    # Send a registration message to the host containing the player's address,
    # name and the ports (server + client) the player is listening on
    def register(self):
        # check if there is a connection established to the host
        if not self.socket:
            print("No connection to host")
            return

        print("Sending registration message")
        print("player: ", self.player)
        self.socket.sendall(
            pickle.dumps({"type": "register", "player": self.player})
        )

    # Handle registration accepted message and store the bingo card
    def handle_registration_accepted(self, data):
        self.bingo_card = data["card"]  
        self.socket.sendall(pickle.dumps({"type": "ack"}))
        print("Registration accepted, here's your bingo card: ")
        self.player = data["player"]
        self.establish_server()
        self.players.append(self.player)
        self.players.remove(self.player)
        self.print_card()

    # Set up a server socket to listen to other players
    def establish_server(self):
        print(f"self.player: {self.player}")
        self.server_socket.bind(("", self.port))
        self.server_socket.listen()
        connection_thread = threading.Thread(target= self.establish_connections_with_players)
        connection_thread.start()

    # Handle game start message
    def handle_game_start(self, data):
        print(data["content"])
        self.players = data["connections"]
        self.players.remove(self.player)
        print("Other players: ", self.players)
        self.connect_other_players()
        self.socket.sendall(pickle.dumps({"type": "ack"}))

    # Establish connections with other players
    def establish_connections_with_players(self):
        while len(self.connections) < len(self.players): # Wait until all players have connected
            print("Accepting connections from other players")
            conn, addr = self.server_socket.accept()
            self.connections.append(conn)
            print("Connection established with: ", addr)

        self.listen_to_players_async()

    # Connect to other players
    def connect_other_players(self):
        for player in self.players:
            peer_socket = socket(AF_INET, SOCK_STREAM)
            self.peer_sockets.append(peer_socket)
            print("Connecting to " + player["address"], player["server_port"])
            peer_socket.connect((player["address"], player["server_port"]))

    def listen_to_players_async(self):
        for conn in self.connections:
            listen_thread = threading.Thread(target=self.listen_to_player, args=(conn,))
            listen_thread.start()

    def listen_to_player(self, conn):
        conn.settimeout(1) # Set connection timeout to 1 second in order to regularly check if a bingo has been shouted
        while not self.game_over:
            try:
                data = conn.recv(1024)
                data = pickle.loads(data)
                #print("Received message from player: ", data)
                if data["type"] == "check_numbers":
                    self.check_peer_numbers(data)
                elif data["type"] == "check_peer_numbers_response":
                    if not data["is_ok"]:
                        print("Peer numbers not ok")
                        #TODO handle syncing numbers (bingo_host)
            except timeout:
                continue

    def check_peer_numbers(self, data):
        peer_numbers = data["my_numbers"]
        is_ok = len(peer_numbers) == len(self.drawn_numbers) and peer_numbers == self.drawn_numbers
        for peer_socket in self.peer_sockets:
            peer_socket.sendall(
                pickle.dumps({
                    "type": "check_peer_numbers_response",
                    "is_ok": is_ok,
                    "timestamp": datetime.datetime.now(),
                })
            )

    def send_numbers_to_peers(self):
        message_type = "check_numbers"

        for peer_socket in self.peer_sockets:
            peer_socket.sendall(
                pickle.dumps({
                    "type": message_type,
                    "my_numbers": self.drawn_numbers,
                    "timestamp": datetime.datetime.now(),
                    "player": self.name
                })
            )

    # Handle bingo number message
    def handle_bingo_number(self, data):
        print("Number drawn: ", data["number"])
        self.drawn_numbers.append(data["number"])
        self.send_numbers_to_peers()
        self.check_number(data["number"])
        is_bingo = self.check_bingo()
        if is_bingo:
            self.socket.sendall(
                pickle.dumps({
                    "type": "bingo",
                    "card": self.bingo_card,
                    "timestamp": datetime.datetime.now(),
                    "player": self.name
                })
            )
            print("BINGO!")
            self.print_card()

    # Handle end message
    def handle_end_message(self, data):
        self.game_over = True
        print(data["content"])

        for thread in threading.enumerate():
            if thread != threading.current_thread():
                thread.join()

        for conn in self.connections:
            conn.close()

        for peer_socket in self.peer_sockets:
            peer_socket.close()

        self.socket.close()

    # Checks if the given number is in the card
    def check_number(self, number):
        for row in self.bingo_card:
            if number in row:
                # todo: send message to other players that the number was a hit
                print("IT'S A HIT: ", number)
                self.print_card()
                return True
        return False

    # Prints card in a form where each row is a vertical column
    def print_card(self):
        print("B\tI\tN\tG\tO")
        for i in range(5):
            for row in self.bingo_card:
                # if the number has been drawn, print the number in red
                if row[i] in self.drawn_numbers:
                    print("\033[91m{}\033[00m".format(row[i]), end="\t")
                else:
                    print(row[i], end="\t")
            print()

    # Checks if the card has a bingo. A bingo is when a row, column or diagonal has all numbers hit
    def check_bingo(self):
        # check rows
        for row in self.bingo_card:
            if all(number in self.drawn_numbers for number in row):
                return True
        # check columns
        for i in range(5):
            if all(row[i] in self.drawn_numbers for row in self.bingo_card):
                return True
        # check diagonals
        if all(self.bingo_card[i][i] in self.drawn_numbers for i in range(5)):
            return True
        if all(self.bingo_card[i][4-i] in self.drawn_numbers for i in range(5)):
            return True
        return False

    # Handle consensus round message
    def handle_consensus_round(self, data):
        bingo_row = data["numbers"]
        print("Checking consensus on row: ", bingo_row)
        is_bingo = set(bingo_row).issubset(set(self.drawn_numbers))
        print("Sending consensus response. Is bingo: ", is_bingo)
        self.socket.sendall(
            pickle.dumps({
                "type": "consensus_response",
                "is_bingo": is_bingo,
                "timestamp": datetime.datetime.now(),
            })
        )
        print("Consensus response sent")
    
    # Handle remove player message
    def handle_remove_player(self, data):
        print("Removing player: ", data["player"])
        self.players.remove(data["player"])
        peer_socket = self.peer_sockets[self.players.index(data["player"])]
        peer_socket.close()
        self.peer_sockets.remove(peer_socket)
        connection = self.connections[self.players.index(data["player"])]
        connection.close()
        self.connections.remove(data["player"]) 

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host",default="",help="host ip")
    parser.add_argument("--port",default=65432,help="host port")
    args = parser.parse_args()
    host = args.host
    port = args.port
    Player(host=host, port=port)
