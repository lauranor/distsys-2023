# The player node class
from socket import *
import pickle

class Player:
    def __init__(self):
        self.bingo_host = "192.168.1.115"
        self.bingo_host_port = 65432
        self.socket = socket(AF_INET, SOCK_STREAM)
        self.socket.connect((self.bingo_host, self.bingo_host_port))
        self.players = []
        self.drawn_numbers = []
        self.bingo_card = []
        self.listen()

    def listen(self):
        while True:
            data = self.socket.recv(1024)
            data = pickle.loads(data)
            # Message from the host that the player has been accepted 
            # Store bingo card from the host
            if data["type"] == "accept_player":
                print("Registration accepted, bingo card here: ", data["card"])   
                self.bingo_card = data["card"]        
                self.socket.sendall(pickle.dumps({"type": "ack"}))
            # Message from the host that the game is starting
            # todo: establish connections to other players
            elif data["type"] == "start_message":
                print(data["content"])
                print("All players: ", data["connections"])    
                self.socket.sendall(pickle.dumps({"type": "ack"}))
            # Message from the host that a new number has been drawn
            elif data["type"] == "bingo_number":
                print("Number drawn: ", data["number"])
            # Message from the host that the game is over
            elif data["type"] == "end_message":
                print(data["message"])
                self.socket.close()
                break
            # todo at least:
            # handle card hit
            # handle sync request
            # handle sync response
            # handle bingo
            # handle winner confirmation
            

if __name__ == "__main__":
    Player()


