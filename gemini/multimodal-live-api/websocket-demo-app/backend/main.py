import asyncio
import json
import logging
import websockets
from websockets.exceptions import ConnectionClosed
from websockets.legacy.protocol import WebSocketCommonProtocol
from websockets.legacy.server import WebSocketServerProtocol
from websockets.protocol import State

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HOST = "generativelanguage.googleapis.com"
WEBSOCKET_PATH = "/v1beta/models/{model}:streamGenerateContent"
MODEL = "gemini-2.0-flash-exp"
DEBUG = True

class WebSocketError(Exception):
    def __init__(self, message, code=1011):
        super().__init__(message)
        self.code = code

def get_websocket_state(ws) -> State:
    """获取 WebSocket 连接状态"""
    try:
        if hasattr(ws, 'state'):
            return ws.state
        if hasattr(ws, 'connection'):
            return ws.connection.state
        return State.CLOSED
    except Exception:
        return State.CLOSED

async def is_websocket_open(ws) -> bool:
    """检查 WebSocket 连接是否打开"""
    try:
        return get_websocket_state(ws) is State.OPEN
    except Exception:
        return False

async def close_websocket(ws, code=1000, reason="Normal closure"):
    """安全地关闭 WebSocket 连接"""
    try:
        if hasattr(ws, 'close') and await is_websocket_open(ws):
            await ws.close(code, reason)
    except Exception as e:
        logger.error(f"Error closing WebSocket: {e}")

async def send_websocket_message(ws, message):
    """安全地发送 WebSocket 消息"""
    try:
        if await is_websocket_open(ws):
            if isinstance(message, dict):
                await ws.send(json.dumps(message))
            else:
                await ws.send(message)
            return True
    except Exception as e:
        logger.error(f"Error sending message: {e}")
    return False

async def proxy_task(
    source_ws: WebSocketCommonProtocol, target_ws: WebSocketCommonProtocol,
    name: str = "unnamed"
) -> None:
    """
    Forwards messages from the source WebSocket to the target WebSocket.
    """
    try:
        logger.info(f"[{name}] Starting proxy task")
        async for message in source_ws:
            if not await is_websocket_open(target_ws):
                logger.info(f"[{name}] Target WebSocket is closed")
                break
                
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                    logger.info(f"[{name}] Forwarding JSON message: {data}")
                except json.JSONDecodeError:
                    logger.info(f"[{name}] Forwarding text message: {message}")
                
                if not await send_websocket_message(target_ws, message):
                    break
            elif isinstance(message, bytes):
                logger.info(f"[{name}] Forwarding binary message, length: {len(message)}")
                if not await send_websocket_message(target_ws, message):
                    break
                    
    except ConnectionClosed as e:
        logger.error(f"[{name}] Connection closed: code={e.code}, reason={e.reason}")
        raise WebSocketError(f"Connection closed: {e.reason}", e.code)
    except Exception as e:
        logger.error(f"[{name}] Error in proxy task: {e}")
        raise WebSocketError(str(e))

async def create_proxy(
    client_websocket: WebSocketCommonProtocol, api_key: str, service_url: str = None
) -> None:
    """
    Establishes a WebSocket connection to the server and creates two tasks for
    bidirectional message forwarding between the client and the server.
    """
    server_websocket = None
    
    try:
        if service_url:
            uri = f"{service_url}?key={api_key}"
        else:
            uri = f"wss://{HOST}{WEBSOCKET_PATH.format(model=MODEL)}?key={api_key}"
        
        logger.info(f"Connecting to {uri}")
        
        try:
            server_websocket = await websockets.connect(
                uri,
                ping_interval=20,     # 启用 ping 保持连接
                max_size=None,        # 禁用消息大小限制
                compression=None,     # 禁用压缩
                close_timeout=5,      # 设置关闭超时
            )
        except Exception as e:
            logger.error(f"Failed to connect to server: {e}")
            raise WebSocketError(f"Failed to connect to server: {e}")
        
        logger.info("Connected to server")
        
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
        logger.info("Sent setup message")
        
        # 创建双向代理任务
        client_to_server_task = asyncio.create_task(
            proxy_task(client_websocket, server_websocket, "client->server")
        )
        server_to_client_task = asyncio.create_task(
            proxy_task(server_websocket, client_websocket, "server->client")
        )
        
        try:
            # 等待任一任务完成
            done, pending = await asyncio.wait(
                [client_to_server_task, server_to_client_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # 取消剩余任务
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            # 检查是否有任务出错
            for task in done:
                try:
                    await task
                except Exception as e:
                    logger.error(f"Task failed with error: {e}")
                    raise
            
        except Exception as e:
            logger.error(f"Error during message forwarding: {e}")
            raise WebSocketError(str(e))
            
    except WebSocketError as e:
        await send_websocket_message(client_websocket, {"error": str(e)})
        await close_websocket(client_websocket, e.code, str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await send_websocket_message(client_websocket, {"error": str(e)})
        await close_websocket(client_websocket, 1011, str(e))
    finally:
        # 确保服务器连接被关闭
        if server_websocket:
            await close_websocket(server_websocket)

async def handle_client(client_websocket: WebSocketServerProtocol) -> None:
    """
    Handles a new client connection, expecting the first message to contain an API key.
    """
    logger.info("New client connection...")
    try:
        # 等待认证消息
        auth_message = await asyncio.wait_for(client_websocket.recv(), timeout=10.0)
        logger.info("Received auth message")
        
        try:
            auth_data = json.loads(auth_message)
            api_key = None
            service_url = None
            
            if isinstance(auth_data, dict):
                api_key = auth_data.get("api_key")
                service_url = auth_data.get("service_url")
            else:
                api_key = auth_message
                
            if not api_key:
                raise WebSocketError("API key not found in auth message", 4000)
                
            await create_proxy(client_websocket, api_key, service_url)
                
        except json.JSONDecodeError:
            # 如果不是 JSON，假设整个消息就是 API key
            await create_proxy(client_websocket, auth_message)
            
    except asyncio.TimeoutError:
        logger.error("Authentication timeout")
        await close_websocket(client_websocket, 4001, "Authentication timeout")
    except WebSocketError as e:
        logger.error(f"WebSocket error: {e}")
        await send_websocket_message(client_websocket, {"error": str(e)})
        await close_websocket(client_websocket, e.code, str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await send_websocket_message(client_websocket, {"error": str(e)})
        await close_websocket(client_websocket, 1011, str(e))

async def main() -> None:
    """
    Main entry point for the WebSocket proxy server.
    """
    async with websockets.serve(handle_client, "localhost", 8000):
        logger.info("WebSocket server running on ws://localhost:8000")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
