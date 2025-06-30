from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Dict, List, Optional
import uuid
import json
import random

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------- ENUM & MODELS ----------------------

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

# ---------------------- GLOBALS ----------------------

games: Dict[str, GameState] = {}
player_to_room: Dict[str, str] = {}

# ---------------------- 카드 정의 ----------------------

SEOTTA_CARDS = [
    Card(1, "bright", "송학", 20), Card(1, "ribbon", "송패", 5), Card(1, "junk", "송끌", 1),
    Card(2, "animal", "매조", 10), Card(2, "ribbon", "매패", 5), Card(2, "junk", "매끌", 1),
    Card(3, "bright", "벚광", 20), Card(3, "ribbon", "벚패", 5), Card(3, "junk", "벚끌", 1),
    Card(4, "animal", "등새", 10), Card(4, "ribbon", "등패", 5), Card(4, "junk", "등끌", 1),
    Card(5, "animal", "창다리", 10), Card(5, "ribbon", "창패", 5), Card(5, "junk", "창끌", 1),
    Card(6, "animal", "모란나비", 10), Card(6, "ribbon", "모란패", 5), Card(6, "junk", "모란끌", 1),
    Card(7, "animal", "싸리멧돼지", 10), Card(7, "ribbon", "싸리패", 5), Card(7, "junk", "싸리끌", 1),
    Card(8, "bright", "억새달", 20), Card(8, "animal", "억새기러기", 10), Card(8, "junk", "억새끌", 1),
    Card(9, "animal", "국화술잔", 10), Card(9, "ribbon", "국화패", 5), Card(9, "junk", "국화끌", 1),
    Card(10, "animal", "단풍사슴", 10), Card(10, "ribbon", "단풍패", 5), Card(10, "junk", "단풍끌", 1),
    Card(11, "bright", "오동광", 20), Card(11, "junk", "오동끌1", 1), Card(11, "junk", "오동끌2", 1),
    Card(12, "bright", "비광", 20), Card(12, "animal", "비제비", 10), Card(12, "junk", "비끌", 1)
]

# ---------------------- GAME LOGIC ----------------------

def calculate_hand_value(cards: List[Card]) -> tuple[int, str]:
    if len(cards) != 2:
        return 0, "없음"
    card1, card2 = cards

    special = {(1, 2): 100, (1, 4): 99, (1, 9): 98, (1, 10): 97, (4, 10): 96, (4, 6): 95}
    if (card1.month, card2.month) in special or (card2.month, card1.month) in special:
        return special.get((card1.month, card2.month), special.get((card2.month, card1.month))), f"{card1.month}{card2.month}땡"

    if card1.month == card2.month:
        return 90 + card1.month, f"{card1.month}땡"

    total = (card1.month + card2.month) % 10
    return total, ["망통", "1끗", "2끗", "3끗", "4끗", "5끗", "6끗", "7끗", "8끗", "9끗"][total]

def shuffle_deck() -> List[Card]:
    deck = SEOTTA_CARDS.copy()
    random.shuffle(deck)
    return deck

def deal_cards(game: GameState):
    deck = shuffle_deck()
    for i, player in enumerate(game.players):
        player.cards = deck[i*2:i*2+2]
        player.hand_value, player.hand_name = calculate_hand_value(player.cards)

async def broadcast_game_state(game: GameState):
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
                    "cards": [asdict(c) for c in p.cards],
                    "handValue": p.hand_value,
                    "handName": p.hand_name,
                    "status": p.status.value,
                    "isReady": p.is_ready
                } for p in game.players
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
    for p in game.players:
        if p.websocket:
            try:
                await p.websocket.send_text(json.dumps(game_data))
            except:
                pass

def start_new_round(game: GameState):
    game.phase = GamePhase.BETTING
    game.current_player = 0
    game.pot = 0
    for p in game.players:
        p.status = PlayerStatus.PLAYING
        p.current_bet = 0
        p.is_ready = False
    deal_cards(game)

# ---------------------- API ----------------------

@app.get("/")
async def root():
    return {"message": "섯다 게임 서버가 실행 중입니다!"}

@app.post("/rooms")
async def create_room(request: Request):
    data = await request.json()
    player_name = data.get("playerName")

    if not player_name:
        return JSONResponse(status_code=400, content={"error": "플레이어 이름이 필요합니다."})

    room_id = uuid.uuid4().hex[:6].upper()
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

    return {"roomId": room_id, "message": f"{room_id} 방이 생성되었습니다."}

# ---------------------- WEBSOCKET ----------------------

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

                if room_id not in games:
                    return

                game = games[room_id]

                if len(game.players) >= 2:
                    await websocket.send_text(json.dumps({"type": "error", "data": {"message": "방이 가득 찼습니다."}}))
                    continue

                player = Player(
                    id=player_id, name=player_name, chips=5000,
                    current_bet=0, cards=[], hand_value=0, hand_name="",
                    status=PlayerStatus.WAITING, is_ready=False, websocket=websocket
                )

                game.players.append(player)
                player_to_room[player_id] = room_id

                await broadcast_game_state(game)

            elif message["type"] == "ready":
                game = games.get(room_id)
                player = next((p for p in game.players if p.id == player_id), None)

                if player:
                    player.is_ready = True
                    if len(game.players) == 2 and all(p.is_ready for p in game.players):
                        start_new_round(game)
                    await broadcast_game_state(game)

            elif message["type"] == "bet":
                game = games.get(room_id)
                player = next((p for p in game.players if p.id == player_id), None)

                if not player or game.phase != GamePhase.BETTING or game.players[game.current_player].id != player_id:
                    continue

                action = message["action"]

                if action == "fold":
                    player.status = PlayerStatus.FOLDED
                    winner = next(p for p in game.players if p.id != player_id)
                    winner.chips += game.pot
                    game.winner = winner.name
                    game.phase = GamePhase.FINISHED

                elif action == "call":
                    bet = game.min_bet
                    if player.chips >= bet:
                        player.chips -= bet
                        player.current_bet += bet
                        game.pot += bet
                        game.current_player = (game.current_player + 1) % 2

                        if all(p.status != PlayerStatus.PLAYING or p.current_bet > 0 for p in game.players):
                            game.phase = GamePhase.REVEAL
                            active = [p for p in game.players if p.status != PlayerStatus.FOLDED]
                            if len(active) == 2:
                                winner = max(active, key=lambda p: p.hand_value)
                                winner.chips += game.pot
                                game.winner = winner.name
                                game.phase = GamePhase.FINISHED

                elif action == "half":
                    bet = game.pot // 2
                    if player.chips >= bet:
                        player.chips -= bet
                        player.current_bet += bet
                        game.pot += bet
                        game.current_player = (game.current_player + 1) % 2

                elif action == "all-in":
                    bet = player.chips
                    player.current_bet += bet
                    game.pot += bet
                    player.chips = 0
                    player.status = PlayerStatus.ALL_IN
                    game.current_player = (game.current_player + 1) % 2

                await broadcast_game_state(game)

            elif message["type"] == "new_game":
                game = games.get(room_id)
                if game:
                    start_new_round(game)
                    await broadcast_game_state(game)

    except WebSocketDisconnect:
        if player_id and room_id:
            game = games.get(room_id)
            if game:
                game.players = [p for p in game.players if p.id != player_id]
                if not game.players:
                    del games[room_id]
                else:
                    await broadcast_game_state(game)

            player_to_room.pop(player_id, None)
