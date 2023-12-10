from socket import *
import pickle
import time
import random
import threading

# The bingo host class
class BingoHost:
    def __init__(self):
        self.host = ""
        self.port = 65432
        self.socket = socket(AF_INET, SOCK_STREAM)
        self.connections = []
        self.players = []
        self.numbers = []
        self.drawn_numbers = []
        self.bingo_shouted = False
        self.is_bingo = False
        self.bingo_cards = []
        self.registrations_open = False
        self.game_ongoing = False
        self.send_lock = threading.Lock()
        self.launch()

    # Initialises a new game
    def initialise_new_game(self):
        self.socket.bind((self.host, self.port))
        self.socket.listen()
        self.numbers = list(range(1, 75))
        random.shuffle(self.numbers)
        self.drawn_numbers = []
        self.bingo_shouted = False
        self.is_bingo = False
        self.bingo_cards = []
        self.registrations_open = True

    def launch(self):
        self.initialise_new_game()
        while self.registrations_open:
            print(f"Bingo host started, waiting for players to connect...")
            # Accept new connections from players
            conn, addr = self.socket.accept()
            self.add_player(conn, addr)
            # todo? registration round open for a certain time, then start the game
            if len(self.players) == 2:
                self.registrations_open = False
        self.start_game()

    # Adds a new player to the game
    def add_player(self, conn, addr):
        self.connections.append(conn)
        self.players.append(addr)
        # Generate and send a new bingo card to the connected player
        bingo_card = self.generate_bingo_card()
        print("Sending bingo card to player: ", bingo_card)
        conn.sendall(pickle.dumps({"type": "accept_player", "card": bingo_card}))
        # Wait for acknowledgement from the player
        self.wait_for_ack(conn, message_type="accept_player")
        print(f"Connected by {addr}")

    # Method to send a message to all players
    # consider multicasting?
    def send_message_to_players(self, message, ack_required=False):
        for conn in self.connections:
            conn.sendall(pickle.dumps(message))

        if ack_required:
            # Check for acknowledgements from all players
            with self.send_lock:
                self.wait_for_ack_from_all(message_type=message["type"])

    # Listens for acknowledgements from a single player, returns true if acknowledgement received
    # Returns false and removes the player from the game if no acknowledgement received in time
    def wait_for_ack(self, conn, message_type):
        # Set connection timeout to 2 seconds
        conn.settimeout(2)
        # Set number of retries to 3
        ack_retries = 3
        acknowledgement_received = False
        print(f"Waiting for acknowledgement from {conn.getpeername()} for {message_type}...")
        while ack_retries > 0 and not acknowledgement_received:
            try:
                data = conn.recv(1024)
                data = pickle.loads(data)
                if data["type"] == "ack":
                    print(f"Received acknowledgement from {conn.getpeername()} for {message_type}")
                    acknowledgement_received = True
                    break
            except timeout:
                print(f"No acknowledgement received from {conn.getpeername()} for {message_type}, retrying...")
                ack_retries -= 1
        if not acknowledgement_received:
            print(f"No acknowledgement received for {message_type}.")
            print(f"removing player {conn.getpeername()} from the game and closing connection...")
            self.remove_player(conn)
        return acknowledgement_received

    # Listens for acknowledgements from all players
    def wait_for_ack_from_all(self, message_type):
        for conn in self.connections:
            listen_thread = threading.Thread(target=self.wait_for_ack, args=(conn,))
            listen_thread.start()

    # Removes a player from the game
    def remove_player(self, conn):
        # Send one more message to the player to let them know they're being removed, just in case
        conn.sendall(pickle.dumps({
            "type": "end_message", 
            "content": "You have been removed from the game due to inactivity."
        }))
        self.players.remove(conn.getpeername())
        self.connections.remove(conn)
        conn.close()

    # Starts the game and sends start message to all players containing the connection 
    # information to other players
    def start_game(self):
        print("Starting game...")
        self.game_ongoing = True
        # Send start message to all players, requires acknowledgement from all players
        self.send_message_to_players({
            "type": "start_message",
            "content": "Game starts now!",
            "connections": self.players
        }, ack_required=True)

        # Start drawing numbers and listening to players asynchronously
        self.draw_numbers_async()
        self.listen_to_players_async()

    # Method to draw numbers asynchronously
    def draw_numbers_async(self):
        draw_thread = threading.Thread(target=self.draw_numbers)
        draw_thread.start()

    # Draws random numbers and sends them to all players
    def draw_numbers(self):
        while self.numbers:
            if self.bingo_shouted:
                break
            number = self.numbers.pop(0)
            self.drawn_numbers.append(number)
            print("Number drawn: ", number)
            self.send_message_to_players({"type": "bingo_number", "number": number})
            time.sleep(1)
        if not self.is_bingo and not self.numbers:
            self.end_game("All numbers drawn, no winner this round :(")

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
        print("Generated a new bingo card: ", bingo_card)
        self.bingo_cards.append(bingo_card)
        return bingo_card

    # Listen for messages from a single player
    def listen_to_player(self, conn):
        while self.game_ongoing:
            data = conn.recv(1024)
            data = pickle.loads(data)
            if data["type"] == "bingo":
                self.bingo_shouted = True
                # print that certain player shouted bingo
                print("Bingo shouted by player: ", data["player"])
                self.send_message_to_players({
                    "type": "bingo_check",
                    "content": "Checking if it's a bingo for player " + data["player"]
                })
                self.handle_bingo(data["card"], data["player"], data["timestamp"])

    # Method to start listening to players asynchronously
    # Threading is not the most optimal solution here, but it's the easiest to implement for now
    # todo: consider using asyncio
    def listen_to_players_async(self):
        for conn in self.connections:
            conn.settimeout(None)
            listen_thread = threading.Thread(target=self.listen_to_player, args=(conn,))
            listen_thread.start()

    def handle_bingo(self, card, name, timestamp):
        if self.check_bingo(card):
            # todo: consensus round beofre declaring the winner and setting is_bingo to true
            self.is_bingo = True
            print("IIIIT'S A BINGOOO!")
            self.send_message_to_players({
                "type": "winner_confirmation", 
                "content":f"Player {name} won the round!"
            })
            self.end_game("The round has ended. Thanks for playing!")
        else:
            print("Not a bingo :(")
            self.bingo_shouted = False
            self.send_message_to_players({
                "type": "rejected_bingo",
                "content": "Not a bingo :( Resuming the game..."
            })
            self.draw_numbers_async()

    # Ends the game and closes all connections
    # todo: it's not closing very gracefully, need to fix
    def end_game(self, message):
        self.send_message_to_players({"type": "end_message", "content": message})
        self.game_ongoing = False

        # Wait for threads to complete before closing connections
        for thread in threading.enumerate():
            if thread != threading.current_thread():
                thread.join()

        for conn in self.connections:
            conn.close()
        self.socket.close()

    # Checks if the card has a bingo. A bingo is when a row, column or diagonal has all numbers hit
    def check_bingo(self, card):
        # if the card is not in the list of bingo cards, it's not a valid bingo
        if card not in self.bingo_cards:
            return False
        # check rows
        for row in card:
            if all(number in self.drawn_numbers for number in row):
                return True
        # check columns
        for i in range(5):
            if all(row[i] in self.drawn_numbers for row in card):
                return True
        # check diagonals
        if all(card[i][i] in self.drawn_numbers for i in range(5)):
            return True
        if all(card[i][4-i] in self.drawn_numbers for i in range(5)):
            return True
        return False


if __name__ == "__main__":
    bingo_host = BingoHost()