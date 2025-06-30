from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
import uuid
import random
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class GamePhase(Enum):
    WAITING = "waiting"
    BETTING = "betting"
    REVEAL = "reveal"
    FINISHED = "finished"

class PlayerStatus(Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    FOLDED = "folded"
    ALL_IN = "all-in"

@dataclass
class Card:
    month: int
    type: str
    name: str
    value: int

@dataclass
class Player:
    id: str
    name: str
    chips: int
    current_bet: int
    cards: List[Card]
    hand_value: int
    hand_name: str
    status: PlayerStatus
    is_ready: bool
    websocket: Optional[WebSocket] = None

@dataclass
class GameState:
    id: str
    players: List[Player]
    current_player: int
    phase: GamePhase
    pot: int
    min_bet: int
    max_bet: int
    round: int
    winner: Optional[str] = None

# Game data storage
games: Dict[str, GameState] = {}
player_to_room: Dict[str, str] = {}

# Card definitions for Seotta
SEOTTA_CARDS = [
    # 1월 (소나무)
    Card(1, "bright", "송학", 20),
    Card(1, "ribbon", "송패", 5),
    Card(1, "junk", "송끌", 1),
    # 2월 (매화)
    Card(2, "animal", "매조", 10),
    Card(2, "ribbon", "매패", 5),
    Card(2, "junk", "매끌", 1),
    # 3월 (벚꽃)
    Card(3, "bright", "벚광", 20),
    Card(3, "ribbon", "벚패", 5),
    Card(3, "junk", "벚끌", 1),
    # 4월 (등나무)
    Card(4, "animal", "등새", 10),
    Card(4, "ribbon", "등패", 5),
    Card(4, "junk", "등끌", 1),
    # 5월 (창포)
    Card(5, "animal", "창다리", 10),
    Card(5, "ribbon", "창패", 5),
    Card(5, "junk", "창끌", 1),
    # 6월 (모란)
    Card(6, "animal", "모란나비", 10),
    Card(6, "ribbon", "모란패", 5),
    Card(6, "junk", "모란끌", 1),
    # 7월 (싸리)
    Card(7, "animal", "싸리멧돼지", 10),
    Card(7, "ribbon", "싸리패", 5),
    Card(7, "junk", "싸리끌", 1),
    # 8월 (억새)
    Card(8, "bright", "억새달", 20),
    Card(8, "animal", "억새기러기", 10),
    Card(8, "junk", "억새끌", 1),
    # 9월 (국화)
    Card(9, "animal", "국화술잔", 10),
    Card(9, "ribbon", "국화패", 5),
    Card(9, "junk", "국화끌", 1),
    # 10월 (단풍)
    Card(10, "animal", "단풍사슴", 10),
    Card(10, "ribbon", "단풍패", 5),
    Card(10, "junk", "단풍끌", 1),
    # 11월 (오동)
    Card(11, "bright", "오동광", 20),
    Card(11, "junk", "오동끌1", 1),
    Card(11, "junk", "오동끌2", 1),
    # 12월 (비)
    Card(12, "bright", "비광", 20),
    Card(12, "animal", "비제비", 10),
    Card(12, "junk", "비끌", 1)
]

def calculate_hand_value(cards: List[Card]) -> tuple[int, str]:
    """Calculate the value and name of a 2-card hand in Seotta"""
    if len(cards) != 2:
        return 0, "없음"
    
    card1, card2 = cards
    
    # Special combinations (땡)
    if card1.month == 1 and card2.month == 2:
        return 100, "12땡"
    if card1.month == 1 and card2.month == 4:
        return 99, "14땡"
    if card1.month == 1 and card2.month == 9:
        return 98, "19땡"
    if card1.month == 1 and card2.month == 10:
        return 97, "110땡"
    if card1.month == 4 and card2.month == 10:
        return 96, "410땡"
    if card1.month == 4 and card2.month == 6:
        return 95, "46땡"
    
    # Same month (땡)
    if card1.month == card2.month:
        return 90 + card1.month, f"{card1.month}땡"
    
    # Sum calculation (끗)
    total = (card1.month + card2.month) % 10
    
    names = ["망통", "1끗", "2끗", "3끗", "4끗", "5끗", "6끗", "7끗", "8끗", "9끗"]
    return total, names[total]

def shuffle_deck() -> List[Card]:
    """Shuffle and return a deck of cards"""
    deck = SEOTTA_CARDS.copy()
    random.shuffle(deck)
    return deck

def deal_cards(game: GameState):
    """Deal 2 cards to each player"""
    deck = shuffle_deck()
    card_index = 0
    
    for player in game.players:
        player.cards = deck[card_index:card_index + 2]
        card_index += 2
        
        # Calculate hand value
        player.hand_value, player.hand_name = calculate_hand_value(player.cards)

async def broadcast_game_state(game: GameState):
    """Send game state to all players in the room"""
    game_data = {
        "type": "game_state",
        "data": {
            "id": game.id,
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "chips": p.chips,
                    "currentBet": p.current_bet,
                    "cards": [asdict(card) for card in p.cards],
                    "handValue": p.hand_value,
                    "handName": p.hand_name,
                    "status": p.status.value,
                    "isReady": p.is_ready
                }
                for p in game.players
            ],
            "currentPlayer": game.current_player,
            "phase": game.phase.value,
            "pot": game.pot,
            "minBet": game.min_bet,
            "maxBet": game.max_bet,
            "round": game.round,
            "winner": game.winner
        }
    }
    
    for player in game.players:
        if player.websocket:
            try:
                await player.websocket.send_text(json.dumps(game_data))
            except:
                pass

def start_new_round(game: GameState):
    """Start a new betting round"""
    game.phase = GamePhase.BETTING
    game.current_player = 0
    game.min_bet = 100
    game.pot = 0
    
    # Reset player states
    for player in game.players:
        player.status = PlayerStatus.PLAYING
        player.current_bet = 0
        player.is_ready = False
    
    # Deal new cards
    deal_cards(game)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    player_id = None
    room_id = None
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message["type"] == "join_room":
                room_id = message["roomId"]
                player_id = message["playerId"]
                player_name = message["playerName"]
                
                # Create room if it doesn't exist
                if room_id not in games:
                    games[room_id] = GameState(
                        id=room_id,
                        players=[],
                        current_player=0,
                        phase=GamePhase.WAITING,
                        pot=0,
                        min_bet=100,
                        max_bet=10000,
                        round=1
                    )
                
                game = games[room_id]
                
                # Check if room is full
                if len(game.players) >= 2:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "data": {"message": "방이 가득 찼습니다."}
                    }))
                    continue
                
                # Add player to game
                player = Player(
                    id=player_id,
                    name=player_name,
                    chips=5000,
                    current_bet=0,
                    cards=[],
                    hand_value=0,
                    hand_name="",
                    status=PlayerStatus.WAITING,
                    is_ready=False,
                    websocket=websocket
                )
                
                game.players.append(player)
                player_to_room[player_id] = room_id
                
                await broadcast_game_state(game)
                
            elif message["type"] == "ready":
                if player_id and room_id in games:
                    game = games[room_id]
                    player = next((p for p in game.players if p.id == player_id), None)
                    
                    if player:
                        player.is_ready = True
                        
                        # Check if both players are ready
                        if len(game.players) == 2 and all(p.is_ready for p in game.players):
                            start_new_round(game)
                        
                        await broadcast_game_state(game)
                        
            elif message["type"] == "bet":
                if player_id and room_id in games:
                    game = games[room_id]
                    player = next((p for p in game.players if p.id == player_id), None)
                    
                    if player and game.phase == GamePhase.BETTING and game.players[game.current_player].id == player_id:
                        action = message["action"]
                        
                        if action == "fold":
                            player.status = PlayerStatus.FOLDED
                            # Other player wins
                            winner = next(p for p in game.players if p.id != player_id)
                            winner.chips += game.pot
                            game.winner = winner.name
                            game.phase = GamePhase.FINISHED
                            
                        elif action == "call":
                            bet_amount = game.min_bet
                            if player.chips >= bet_amount:
                                player.chips -= bet_amount
                                player.current_bet += bet_amount
                                game.pot += bet_amount
                                
                                # Move to next player or reveal
                                game.current_player = (game.current_player + 1) % 2
                                if all(p.status != PlayerStatus.PLAYING or p.current_bet > 0 for p in game.players):
                                    game.phase = GamePhase.REVEAL
                                    
                                    # Determine winner
                                    active_players = [p for p in game.players if p.status != PlayerStatus.FOLDED]
                                    if len(active_players) == 2:
                                        winner = max(active_players, key=lambda p: p.hand_value)
                                        winner.chips += game.pot
                                        game.winner = winner.name
                                        game.phase = GamePhase.FINISHED
                        
                        elif action == "half":
                            bet_amount = game.pot // 2
                            if player.chips >= bet_amount:
                                player.chips -= bet_amount
                                player.current_bet += bet_amount
                                game.pot += bet_amount
                                game.current_player = (game.current_player + 1) % 2
                        
                        elif action == "all-in":
                            bet_amount = player.chips
                            player.current_bet += bet_amount
                            game.pot += bet_amount
                            player.chips = 0
                            player.status = PlayerStatus.ALL_IN
                            game.current_player = (game.current_player + 1) % 2
                        
                        await broadcast_game_state(game)
                        
            elif message["type"] == "new_game":
                if player_id and room_id in games:
                    game = games[room_id]
                    start_new_round(game)
                    await broadcast_game_state(game)
                    
    except WebSocketDisconnect:
        # Clean up player
        if player_id and room_id:
            if room_id in games:
                game = games[room_id]
                game.players = [p for p in game.players if p.id != player_id]
                
                if len(game.players) == 0:
                    del games[room_id]
                else:
                    await broadcast_game_state(game)
            
            if player_id in player_to_room:
                del player_to_room[player_id]

@app.get("/")
async def root():
    return {"message": "섯다 게임 서버가 실행 중입니다!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)