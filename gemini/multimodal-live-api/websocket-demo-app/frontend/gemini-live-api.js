class GeminiLiveResponseMessage {
    constructor(data) {
        this.data = "";
        this.type = "";
        this.endOfTurn = data?.serverContent?.turnComplete;

        const parts = data?.serverContent?.modelTurn?.parts;

        if (data?.setupComplete) {
            this.type = "SETUP COMPLETE";
        } else if (parts?.length && parts[0].text) {
            this.data = parts[0].text;
            this.type = "TEXT";
        } else if (parts?.length && parts[0].inlineData) {
            this.data = parts[0].inlineData.data;
            this.type = "AUDIO";
        }
    }
}

class GeminiLiveAPI {
    constructor(proxyUrl, projectId, model, apiHost) {
        this.proxyUrl = proxyUrl;

        this.projectId = projectId;
        this.model = model;
        this.modelUri = `models/${this.model}`;

        this.responseModalities = ["AUDIO"];
        this.systemInstructions = "";

        this.apiHost = apiHost;
        this.serviceUrl = `wss://${this.apiHost}/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent`;

        this.onReceiveResponse = (message) => {
            console.log("Default message received callback", message);
        };

        this.onConnectionStarted = () => {
            console.log("Default onConnectionStarted");
        };

        this.onErrorMessage = (message) => {
            alert(message);
        };

        this.accessToken = "";
        this.websocket = null;

        console.log("Created Gemini Live API object: ", this);
    }

    setProjectId(projectId) {
        this.projectId = projectId;
        this.modelUri = `models/${this.model}`;
    }

    setAccessToken(newAccessToken) {
        console.log("setting access token: ", newAccessToken);
        this.accessToken = newAccessToken;
    }

    connect(accessToken) {
        this.setAccessToken(accessToken);
        this.setupWebSocketToService();
    }

    disconnect() {
        this.webSocket.close();
    }

    sendMessage(message) {
        if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
            const messageStr = JSON.stringify(message);
            console.log("Sending WebSocket message:", messageStr);
            this.webSocket.send(messageStr);
        } else {
            console.error("WebSocket is not open");
            this.onErrorMessage("WebSocket is not open");
        }
    }

    onReceiveMessage(messageEvent) {
        try {
            console.log("Received WebSocket message:", messageEvent.data);
            const response = JSON.parse(messageEvent.data);
            
            if (response.error) {
                console.error("Server error:", response.error);
                this.onErrorMessage(response.error);
                return;
            }

            if (response.candidates && response.candidates[0].content) {
                const message = new GeminiLiveResponseMessage({
                    serverContent: {
                        modelTurn: response.candidates[0].content,
                        turnComplete: !response.candidates[0].finishReason
                    }
                });
                this.onReceiveResponse(message);
            }
        } catch (error) {
            console.error("Error processing message:", error);
            this.onErrorMessage("Error processing message: " + error.message);
        }
    }

    setupWebSocketToService() {
        console.log("connecting: ", this.proxyUrl);

        this.webSocket = new WebSocket(this.proxyUrl);

        this.webSocket.onclose = (event) => {
            console.log("websocket closed: ", event);
            this.onErrorMessage("Connection closed");
        };

        this.webSocket.onerror = (event) => {
            console.log("websocket error: ", event);
            this.onErrorMessage("Connection error");
        };

        this.webSocket.onopen = (event) => {
            console.log("websocket open: ", event);
            this.sendInitialSetupMessages();
            this.onConnectionStarted();
        };

        this.webSocket.onmessage = this.onReceiveMessage.bind(this);
    }

    sendInitialSetupMessages() {
        // 发送认证消息
        const authMessage = {
            api_key: this.accessToken
        };
        this.sendMessage(authMessage);
    }

    sendTextMessage(text) {
        const textMessage = {
            contents: [{
                role: "user",
                parts: [{ text: text }]
            }],
            generation_config: {
                temperature: 0.9,
                top_p: 1,
                top_k: 1,
                max_output_tokens: 2048,
            }
        };
        console.log("Sending text message:", textMessage);
        this.sendMessage(textMessage);
    }

    sendRealtimeInputMessage(data, mime_type) {
        const message = {
            realtime_input: {
                media_chunks: [
                    {
                        mime_type: mime_type,
                        data: data,
                    },
                ],
            },
        };
        this.sendMessage(message);
    }

    sendAudioMessage(base64PCM) {
        this.sendRealtimeInputMessage(base64PCM, "audio/pcm");
    }

    sendImageMessage(base64Image, mime_type = "image/jpeg") {
        this.sendRealtimeInputMessage(base64Image, mime_type);
    }
}

console.log("loaded gemini-live-api.js");
