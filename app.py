#!/usr/bin/env python

import asyncio
import websockets
import logging
import json
import secrets
from connect4 import PLAYER1, PLAYER2, Connect4
from urllib.parse import urlparse
import os
import signal

logging.basicConfig(format="%(message)s", level=logging.DEBUG)


JOIN = {}
WATCH = {}


async def send_history(websocket, game: Connect4):
    for player, column, row in game.moves.copy():
        # code in Connect4 class
        # self.moves.append((player, column, row))
        event = {
            "type": "play",
            "player": player,
            "column": column,
            "row": row,
        }
        await websocket.send(json.dumps(event))


async def error(websocket, message):
    event = {
        "type": "error",
        "message": message,
    }
    await websocket.send(json.dumps(event))


async def start(websocket):
    # Initialize a Connect Four game, the set of WebSocket connections
    # receiving moves from this game, and secret access token.
    game = Connect4()
    connected = {websocket}

    join_key = secrets.token_urlsafe(12)
    JOIN[join_key] = game, connected

    watch_key = secrets.token_urlsafe(12)
    WATCH[watch_key] = game, connected

    try:
        # Send the secret access token to the browser of the first player,
        # where it'll be used for building a "join" link.
        event = {"type": "init", "join": join_key, "watch": watch_key}
        await websocket.send(json.dumps(event))

        print("first player started game", id(game))
        await play(websocket, game, PLAYER1, connected)

    finally:
        del JOIN[join_key]
        del WATCH[watch_key]


async def join(websocket, join_key):
    # Find the Connect Four game.
    try:
        game, connected = JOIN[join_key]
    except KeyError:
        await error(websocket, "Game not found.")
        return
    # Register to receive moves from this game.
    connected.add(websocket)
    try:
        print("second player joined game", id(game))
        await send_history(websocket, game)
        await play(websocket, game, PLAYER2, connected)

    finally:
        connected.remove(websocket)


async def watch(websocket, watch_key):
    # Find the Connect Four game from WATCH.
    try:
        game, connected = WATCH[watch_key]
    except KeyError:
        await error(websocket, "Game not found.")
        return
    connected.add(websocket)
    try:
        print("watcher joined game", id(game))
        await send_history(websocket, game)
        await websocket.wait_closed()
    finally:
        connected.remove(websocket)


async def handler(websocket):
    # Receive and parse the "init" event from the UI.
    message = await websocket.recv()
    event = json.loads(message)
    assert event["type"] == "init"

    if "join" in event:
        # Second player joins an existing game.
        await join(websocket, event["join"])
    elif "watch" in event:
        # Watch an existing game.
        await watch(websocket, event["watch"])
    else:
        # First player starts a new game.
        await start(websocket)


async def play(websocket, game, player, connected):
    async for message in websocket:
        event = json.loads(message)
        if event["type"] != "play":
            raise Exception("Unknown event type: " + event["type"])
        column = event["column"]

        try:
            row = game.play(player, column)

        except RuntimeError as e:
            # invalid move
            event = {
                "type": "error",
                "message": str(e),
            }
            await websocket.send(json.dumps(event))
            continue

        # valid move
        event = {
            "type": "play",
            "player": player,
            "column": column,
            "row": row,
        }
        # for connection in connected:
        #     await connection.send(json.dumps(event))
        websockets.broadcast(connected, json.dumps(event))

        # check for winner
        if game.winner is not None:
            event = {
                "type": "win",
                "player": game.winner,
            }
            # for connection in connected:
            #     await connection.send(json.dumps(event))
            websockets.broadcast(connected, json.dumps(event))

# health check for fly
import http
async def health_check(path, request_headers):
    if path == "/healthz":
        return http.HTTPStatus.OK, [], b"OK\n"
    
async def main():
    # Set the stop condition when receiving SIGTERM.
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)

    async with websockets.serve(
        handler,
        host="",
        port=8080,
        process_request=health_check,
    ):
        await stop
    # port = int(os.environ.get("PORT", "8001"))
    # async with websockets.serve(handler, "", port):
    #     await stop


if __name__ == "__main__":
    asyncio.run(main())
