import asyncio
import json

import websockets
from websockets.legacy.protocol import WebSocketCommonProtocol
from websockets.legacy.server import WebSocketServerProtocol

HOST = "generativelanguage.googleapis.com"
SERVICE_URL = f"wss://{HOST}/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"

MODEL = "gemini-2.0-flash-exp"  # 使用您的实际模型名称
DEBUG = True

async def proxy_task(
    source_ws: WebSocketCommonProtocol, target_ws: WebSocketCommonProtocol
) -> None:
    """
    Forwards messages from the source WebSocket to the target WebSocket.
    """
    try:
        async for message in source_ws:
            if isinstance(message, str):
                try:
                    # 尝试解析 JSON
                    data = json.loads(message)
                    if DEBUG:
                        print(f"Forwarding message: {data}")
                    await target_ws.send(message)
                except json.JSONDecodeError:
                    print(f"Invalid JSON message: {message}")
            elif isinstance(message, bytes):
                if DEBUG:
                    print(f"Forwarding binary message, length: {len(message)}")
                await target_ws.send(message)
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"Error in proxy_task: {e}")


async def create_proxy(
    client_websocket: WebSocketCommonProtocol, api_key: str, service_url: str = None
) -> None:
    """
    Establishes a WebSocket connection to the server and creates two tasks for
    bidirectional message forwarding between the client and the server.

    Args:
        client_websocket: The WebSocket connection of the client.
        api_key: The API key for authentication with the server.
        service_url: Optional service URL provided by the client.
    """
    if service_url:
        uri = f"{service_url}?key={api_key}"
    else:
        uri = f"wss://{HOST}/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={api_key}"
    
    print(f"Connecting to {uri}")

    try:
        async with websockets.connect(
            uri,
            ping_interval=None,  # 禁用 ping 以避免超时问题
            max_size=None,      # 禁用消息大小限制
            compression=None    # 禁用压缩
        ) as server_websocket:
            # Send initial setup message
            setup_msg = {
                "contents": [{
                    "role": "user",
                    "parts": [{"text": "Hello"}]
                }],
                "tools": [],
                "safety_settings": [],
                "generation_config": {
                    "stop_sequences": [],
                    "temperature": 0.9,
                    "top_p": 1,
                    "top_k": 1,
                    "max_output_tokens": 2048,
                }
            }
            
            await server_websocket.send(json.dumps(setup_msg))
            print("Sent setup message")
            
            # Create bidirectional proxy tasks
            client_to_server_task = asyncio.create_task(
                proxy_task(client_websocket, server_websocket)
            )
            server_to_client_task = asyncio.create_task(
                proxy_task(server_websocket, client_websocket)
            )
            
            try:
                await asyncio.gather(client_to_server_task, server_to_client_task)
            except Exception as e:
                print(f"Error during message forwarding: {e}")
                if not client_websocket.closed:
                    await client_websocket.close(1011, str(e))
                raise
                
    except Exception as e:
        print(f"Connection error: {e}")
        error_msg = {"error": str(e)}
        if not client_websocket.closed:
            await client_websocket.send(json.dumps(error_msg))
            await client_websocket.close(1011, str(e))


async def handle_client(client_websocket: WebSocketServerProtocol) -> None:
    """
    Handles a new client connection, expecting the first message to contain an API key.
    Establishes a proxy connection to the server upon successful authentication.

    Args:
        client_websocket: The WebSocket connection of the client.
    """
    print("New connection...")
    try:
        # Wait for the first message from the client
        auth_message = await asyncio.wait_for(client_websocket.recv(), timeout=5.0)
        print(f"Received auth message: {auth_message}")
        
        try:
            auth_data = json.loads(auth_message)
            if isinstance(auth_data, dict):
                bearer_token = auth_data.get("bearer_token")
                if bearer_token:
                    try:
                        token_data = json.loads(bearer_token)
                        api_key = token_data.get("api_key")
                    except json.JSONDecodeError:
                        api_key = bearer_token
                else:
                    api_key = auth_data.get("api_key")
                
                service_url = auth_data.get("service_url")
                
                if not api_key:
                    raise ValueError("API key not found in auth message")
                    
                await create_proxy(client_websocket, api_key, service_url)
            else:
                # 如果消息不是字典，假设它就是 API key
                await create_proxy(client_websocket, auth_message)
                
        except json.JSONDecodeError as e:
            # 如果不是 JSON，假设整个消息就是 API key
            await create_proxy(client_websocket, auth_message)
            
    except asyncio.TimeoutError:
        print("Authentication timeout")
        await client_websocket.close(1008, "Authentication timeout")
    except Exception as e:
        print(f"Error during authentication: {e}")
        error_msg = {"error": str(e)}
        await client_websocket.send(json.dumps(error_msg))
        await client_websocket.close(1008, str(e))


async def main() -> None:
    """
    Starts the WebSocket server and listens for incoming client connections.
    """
    async with websockets.serve(handle_client, "localhost", 8000):
        print("Running websocket server localhost:8000...")
        # Run forever
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
