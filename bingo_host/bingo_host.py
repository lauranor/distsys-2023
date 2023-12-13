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
        self.bingo = None
        self.bingo_cards = []
        self.registration_open = False
        self.game_ongoing = False
        self.consensus = {}
        self.send_lock = threading.Lock()
        self.bingo_shouted_event = threading.Event()  # Initialize event flag
        self.launch()

    # Initialises a new game
    def initialise_new_game(self):
        self.socket.bind((self.host, self.port))
        self.socket.listen()
        self.numbers = list(range(1, 75))
        random.shuffle(self.numbers)
        self.drawn_numbers = []
        self.bingo_cards = []
        self.registration_open = True
        self.game_ongoing = False
        self.consensus = {}
        self.bingo_shouted_event.clear()

    def launch(self):
        self.initialise_new_game()
        while self.registration_open:
            print(f"Bingo host started, waiting for players to connect...")
            # Accept new connections from players
            conn, addr = self.socket.accept()
            self.add_player(conn, addr)
            # todo? registration round open for a certain time, then start the game
            if len(self.players) == 3:
                self.registration_open = False
        self.start_game()

    # Adds a new player to the game and sends them a bingo card
    def add_player(self, conn, addr):
        self.connections.append(conn)
        data = conn.recv(1024)
        data = pickle.loads(data)
        if data["type"] == "register": 
            player_data = data["player"]
            player = {
                "address": addr[0], 
                "client_port": addr[1], 
                "server_port": player_data["server_port"], 
                "name": player_data["name"]
            }
            print("Received registration from player: ", player)
            self.players.append(player)
            # Generate and send a new bingo card to the connected player
            bingo_card = self.generate_bingo_card()
            print("Sending bingo card to player: ", bingo_card)
            conn.sendall(pickle.dumps({
                "type": "accept_player", 
                "card": bingo_card, 
                "player": player
            }))

            # Wait for acknowledgement from the player
            self.wait_for_response(conn, message_type="accept_player", response_type="ack")
            print(f"Connected by {addr}")

    # Method to send a message to all players
    # If response_type is not None, wait for response from all players
    # consider multicasting?
    def send_message_to_players(self, message, response_type=None):
        for conn in self.connections:
            conn.sendall(pickle.dumps(message))

        if response_type is not None:
            # Wait for response from all players
            with self.send_lock:
                self.wait_for_response_from_all(message_type=message["type"], response_type=response_type)

    # Listens for response from a single player, sets response_received to true if a response is received
    # Removes the player from the game if no response received in time
    def wait_for_response(self, conn, message_type, response_type):
        # Set connection timeout to 3 seconds
        conn.settimeout(3)
        # Set number of retries to 3
        retries = 3
        response_received = False
        print(f"Waiting for response from {conn.getpeername()} for {message_type}...")
        while retries > 0 and not response_received:
            try:
                data = conn.recv(1024)
                data = pickle.loads(data)
                # Handle acknowledgement
                if response_type == "ack" and data["type"] == "ack":
                    print(f"Received acknowledgement from {conn.getpeername()} for {message_type}")
                    response_received = True
                    break
                # Handle consensus response
                elif response_type == "consensus_response" and data["type"] == "consensus_response":
                    print(f"Received bingo check response from {conn.getpeername()}: {data['is_bingo']}")
                    response_received = True
                    with self.send_lock:
                        self.consensus[conn.getpeername()] = data["is_bingo"]
                    break
            except timeout:
                print(f"No response received from {conn.getpeername()} for {message_type}, retrying...")
                retries -= 1
        if not response_received:
            print(f"No response received for {message_type}.")
            print(f"Removing player {conn.getpeername()} from the game and closing connection...")
            self.remove_player(conn)
        return response_received

    # Listens for response from all players
    def wait_for_response_from_all(self, message_type, response_type):
        for conn in self.connections:
            listen_thread = threading.Thread(target=self.wait_for_response, args=(conn, message_type, response_type))
            listen_thread.start()

    # Removes a player from the game
    def remove_player(self, conn):
        # Send one more message to the player to let them know they're being removed, just in case
        conn.sendall(pickle.dumps({
            "type": "end_message", 
            "content": "You have been removed from the game due to inactivity."
        }))
        # Find the player in the list of players
        player = next((player for player in self.players if player["address"] == conn.getpeername()[0]), None)  
        # Remove the player from the list of players and close the connection
        if player is not None:
            self.players.remove(player)
        self.connections.remove(conn)
        conn.close()
        # inform all players that a player has been removed
        self.send_message_to_players({
            "type": "player_removed", 
            "content": "Player " + player["name"] + " has been removed from the game due to inactivity."
        })

    # Starts the game and sends start message to all players containing the connection 
    # information to other players
    def start_game(self):
        print("Starting game...")

        # Send start message to all players, requires acknowledgement from all players
        self.send_message_to_players({
            "type": "start_message",
            "content": "Game starts now!",
            "connections": self.players
        }, response_type="ack")

        self.game_ongoing = True
        time.sleep(1)

        # Start drawing numbers and listening to players asynchronously while the game is ongoing
        while self.game_ongoing:
            self.initiate_game_loop()

    # Initiates the game loop
    def initiate_game_loop(self):
        self.draw_numbers_async()
        self.listen_to_players_async()
        # Wait for a bingo to be shouted
        while self.bingo is None:
            time.sleep(1)
        self.handle_bingo()

    # Method to draw numbers asynchronously
    def draw_numbers_async(self):
        draw_thread = threading.Thread(target=self.draw_numbers)
        draw_thread.start()

    # Draws random numbers and sends them to all players
    def draw_numbers(self):
        while self.numbers:
            if self.bingo_shouted_event.is_set():
                break
            number = self.numbers.pop(0)
            self.drawn_numbers.append(number)
            print("Number drawn: ", number)
            self.send_message_to_players({"type": "bingo_number", "number": number})
            time.sleep(1)
        # If all numbers have been drawn and no bingo has been shouted, end the game
        if not self.bingo_shouted_event.is_set() and not self.numbers:
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

    # Listens for messages from a single player
    def listen_to_player(self, conn):
        conn.settimeout(1) # Set connection timeout to 1 second in order to regularly check if a bingo has been shouted
        while not self.bingo_shouted_event.is_set() and self.game_ongoing:
            try:
                data = conn.recv(1024)
                data = pickle.loads(data)
                print("Received message from player: ", data)
                if data["type"] == "bingo":
                    self.handle_bingo_shouted(data)
                    break
            except timeout:
                continue

    # Handles bingo shouted by a player
    def handle_bingo_shouted(self, data):
        # If a bingo has already been shouted, ignore the message
        # todo: handle the case where multiple players shout bingo at the same time
        # for example use a list of all bingos shouted and compare the timestamps
        if self.bingo_shouted_event.is_set():
            return
        print("Bingo shouted by player: ", data["player"])
        self.bingo = {
            "card": data["card"],
            "player": data["player"],
            "confirmed": False,
            "timestamp": data["timestamp"]
            }
        self.bingo_shouted_event.set()  # Set the event flag

    # Method to start listening to players asynchronously
    # Threading is not the most optimal solution here, but it's the easiest to implement for now
    # todo: consider using asyncio
    def listen_to_players_async(self):
        for conn in self.connections:
            listen_thread = threading.Thread(target=self.listen_to_player, args=(conn,))
            listen_thread.start()

    def handle_bingo(self):
        self.send_message_to_players({
            "type": "bingo_check",
            "content": "Checking if it's a bingo for player " + self.bingo["player"]
        })
        bingo_row = self.get_bingo_row(self.bingo["card"])
        if bingo_row is not None:
            # Consensus round - ask all players if they agree it's a bingo
            is_consensus = self.is_consensus(bingo_row)
            self.handle_consensus_round_result(is_consensus)
        else:
            self.handle_non_bingo()

    # Handles consensus round result
    # If consenseus is reached, inform all players that it's a bingo and end the game
    # Otherwise inform all players that it's not a bingo and resume the game
    def handle_consensus_round_result(self, is_consensus):
        if is_consensus:
            self.bingo["confirmed"] = True
            print("Bingo confirmed!")
            self.send_message_to_players({
                "type": "winner_confirmation", 
                "content":"IIIIT'S A BINGOOO! Player " + self.bingo["player"] + " won the round!"
            })
            self.end_game("The round has ended. Thanks for playing!")
        else:
            # todo: special handling for when consensus is not reached? otherwise the player will keep shouting bingo
            self.handle_non_bingo()

    # Handles a non-bingo
    def handle_non_bingo(self):
        print("Not a bingo :(")
        self.send_message_to_players({
            "type": "rejected_bingo",
            "content": "Not a bingo :( Resuming the game..."
        })
        self.bingo_shouted_event.clear()
        self.bingo = None

    # Ends the game and closes all connections
    def end_game(self, message):
        print("Ending the game...")
        self.send_message_to_players({"type": "end_message", "content": message})
        self.game_ongoing = False

        # Wait for threads to complete before closing connections
        for thread in threading.enumerate():
            if thread != threading.current_thread():
                thread.join()

        for conn in self.connections:
            conn.close()
        self.socket.close()

    # Checks if the card has a bingo. If a bingo is found, return the numbers that form the bingo
    # A bingo is when a row, column or diagonal has all numbers hit
    def get_bingo_row(self, card):
        # if the card is not in the list of bingo cards, it's not a valid bingo
        if card not in self.bingo_cards:
            print("Card not found in the list of bingo cards, not a valid bingo.")
            return None
        # check rows
        for row in card:
            if all(number in self.drawn_numbers for number in row):
                return row
        # check columns
        for i in range(5):
            if all(row[i] in self.drawn_numbers for row in card):
                return [row[i] for row in card]
        # check diagonals
        if all(card[i][i] in self.drawn_numbers for i in range(5)):
            return [card[i][i] for i in range(5)]
        if all(card[i][4-i] in self.drawn_numbers for i in range(5)):
            return [card[i][4-i] for i in range(5)]
        print("No bingo found.")
        return None

    # Handle consensus round
    def is_consensus(self, bingo_row):
        self.send_message_to_players({  
                "type": "consensus_round",
                "numbers": bingo_row
            }, response_type="consensus_response")

        # Wait for all responses to arrive
        while True:
            if len(self.consensus) == len(self.connections):
                break

        # Count the number of true and false values in the consensus dictionary
        true_count = sum(value for value in self.consensus.values() if value)
        false_count = sum(not value for value in self.consensus.values() if not value)
        self.consensus = {} # Reset the consensus dictionary
        # If the number of true values is greater than the number of false values, consensus is reached
        if true_count > false_count:
            print("Consensus reached, it's a bingo!")
            return True
        print("Consensus not reached, resuming the game...")
        return False

if __name__ == "__main__":
    bingo_host = BingoHost()