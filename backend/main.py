from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Dict, List, Optional
import uuid
import json
import random

from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ------------------- MySQL + SQLAlchemy 설정 -------------------

SQLALCHEMY_DATABASE_URL = "mysql+pymysql://admin:1234@localhost:3306/poker_db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=True, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# ------------------- DB 모델 -------------------

class GameRoom(Base):
    __tablename__ = "game_rooms"

    id = Column(String(6), primary_key=True, index=True)
    player_count = Column(Integer, default=0)
    phase = Column(String(20), default="waiting")

# 테이블이 없으면 생성
Base.metadata.create_all(bind=engine)

# ------------------- FastAPI 앱 -------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://sutda-git-master-taehyun00s-projects.vercel.app"
    ],
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
    Card(1, "bright", "송학", 20), Card(1, "ribbon", "송파", 5), Card(1, "junk", "송클", 1),
    Card(2, "animal", "매조", 10), Card(2, "ribbon", "매파", 5), Card(2, "junk", "매클", 1),
    Card(3, "bright", "뱃광", 20), Card(3, "ribbon", "뱃파", 5), Card(3, "junk", "뱃클", 1),
    Card(4, "animal", "등사", 10), Card(4, "ribbon", "등파", 5), Card(4, "junk", "등클", 1),
    Card(5, "animal", "창다리", 10), Card(5, "ribbon", "창파", 5), Card(5, "junk", "창클", 1),
    Card(6, "animal", "모란나비", 10), Card(6, "ribbon", "모란파", 5), Card(6, "junk", "모란클", 1),
    Card(7, "animal", "사리머드", 10), Card(7, "ribbon", "사리파", 5), Card(7, "junk", "사리클", 1),
    Card(8, "bright", "엉사달", 20), Card(8, "animal", "엉기러기", 10), Card(8, "junk", "엉클", 1),
    Card(9, "animal", "국화술잔", 10), Card(9, "ribbon", "국화파", 5), Card(9, "junk", "국화클", 1),
    Card(10, "animal", "단풍사승", 10), Card(10, "ribbon", "단풍파", 5), Card(10, "junk", "단풍클", 1),
    Card(11, "bright", "오동광", 20), Card(11, "junk", "오동클1", 1), Card(11, "junk", "오동클2", 1),
    Card(12, "bright", "비광", 20), Card(12, "animal", "비제비", 10), Card(12, "junk", "비클", 1)
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
def create_room():
    db = SessionLocal()
    try:
        room_id = uuid.uuid4().hex[:6].upper()
        new_room = GameRoom(id=room_id, player_count=0, phase="waiting")
        db.add(new_room)
        db.commit()
        db.refresh(new_room)

        games[room_id] = GameState(
            id=room_id,
            players=[],
            current_player=0,
            phase=GamePhase.WAITING,
            pot=0,
            min_bet=100,
            max_bet=1000,
            round=0,
            winner=None
        )

        return {"roomId": new_room.id}
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()

@app.get("/rooms")
def get_rooms():
    db = SessionLocal()
    try:
        rooms = db.query(GameRoom).all()
        return [{"id": r.id, "player_count": r.player_count, "phase": r.phase} for r in rooms]
    finally:
        db.close()

@app.get("/rooms/{room_id}")
def get_room(room_id: str):
    db = SessionLocal()
    try:
        room = db.query(GameRoom).filter(GameRoom.id == room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        return {
            "id": room.id,
            "player_count": room.player_count,
            "phase": room.phase
        }
    finally:
        db.close()
