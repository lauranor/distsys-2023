from socket import *
import pickle
import time
import random

# The bingo host class
class BingoHost:
    def __init__(self):
        self.host = ""
        self.port = 65432
        self.socket = socket(AF_INET, SOCK_STREAM)
        self.socket.bind((self.host, self.port))
        self.socket.listen()
        self.connections = []
        self.players = []
        print(socket.getsockname(self.socket))
        self.listen()

    def listen(self):
        while True:
            print(f"Bingo host started, waiting for players to connect...")
            # Accept new connections from players
            conn, addr = self.socket.accept()
            self.connections.append(conn)
            self.players.append(addr)
            # Send a new bingo card to the player who just connected
            conn.sendall(pickle.dumps({"type": "accept_player", "card": self.generate_bingo_card()}))
            # todo: wait for acknowledgement + handle non-responding players
            #data = conn.recv(1024)
            #data = pickle.loads(data)
            print(f"Connected by {addr}")
            # For testing purposees starts the game already when only one player has registered
            # todo? registration round open for a certain time, then start the game
            if len(self.players) == 1:
                self.start_game()

                
    # Starts the game and sends start message to all players containing the connection information to other players
    def start_game(self):
        print("Starting game...")
        for conn in self.connections:
            conn.sendall(pickle.dumps({"type": "start_message", "content": "Game starts now!", "connections": self.players}))
            # todo: wait for acknowledgement + handle non-responding players
            #data = conn.recv(1024)
            #data = pickle.loads(data)
        self.draw_numbers()

    # Draws random numbers and sends them to all players
    def draw_numbers(self):
        numbers = list(range(1, 75))
        random.shuffle(numbers)
        # for testing draw only 10 numbers, in real game 75 or until a winner is found
        for number in numbers[:9]:
            print("Number drawn: ", number)
            for conn in self.connections:
                conn.sendall(pickle.dumps({"type": "bingo_number", "number": number}))
            time.sleep(1)
        print("10 test numbers drawn, game over")
        # todo: extract end game logic to a separate method
        for conn in self.connections:
            conn.sendall(pickle.dumps({"type": "end_message", "message": "Game over, no winner found for this round"}))
        self.socket.close()

    # Generates a new bingo 5 x 5 bingo card
    # 1st column (B) numbers between 1-15
    # 2nd column (I) numbers between 16-30
    # 3rd column (N) numbers between 31-45
    # 4th column (G) numbers between 46-60
    # 5th column (O) numbers between 61-75
    def generate_bingo_card(self):
        bingo_card = []
        for i in range(1, 76, 15):  # Adjusting the range for each row
            numbers = random.sample(range(i, i + 15), 5)
            bingo_card.append(numbers)
        print(bingo_card)
        return bingo_card

if __name__ == "__main__":
    BingoHost()
