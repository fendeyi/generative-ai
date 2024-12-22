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

        this.apiHost = apiHost;
        this.serviceUrl = `wss://${this.apiHost}/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent`;

        this.responseModalities = ["AUDIO"];
        this.systemInstructions = "";

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
        this.webSocket = null;
        this.connecting = false;

        this.maxRetries = 3;
        this.retryCount = 0;
        this.retryDelay = 1000; // 1 second

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
        this.accessToken = accessToken;
        this.retryCount = 0;
        console.log("Connecting with access token");
        this.setupWebSocketToService();
    }

    disconnect() {
        this.retryCount = this.maxRetries; // 防止重连
        if (this.webSocket) {
            try {
                this.webSocket.close(1000, "Client disconnecting");
            } catch (error) {
                console.error("Error closing WebSocket:", error);
            }
            this.webSocket = null;
        }
    }

    sendMessage(message) {
        if (!this.webSocket) {
            console.error("No WebSocket connection");
            this.onErrorMessage("No connection available");
            return;
        }

        if (this.webSocket.readyState !== WebSocket.OPEN) {
            console.error("WebSocket is not open, state:", this.webSocket.readyState);
            this.onErrorMessage("Connection is not ready");
            return;
        }

        try {
            const messageStr = JSON.stringify(message);
            console.log("Sending WebSocket message:", messageStr);
            this.webSocket.send(messageStr);
        } catch (error) {
            console.error("Error sending message:", error);
            this.onErrorMessage("Failed to send message: " + error.message);
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
        if (this.connecting) {
            console.log("Connection attempt already in progress");
            return;
        }

        if (this.webSocket) {
            console.log("Closing existing WebSocket connection");
            try {
                this.webSocket.close();
            } catch (error) {
                console.error("Error closing existing connection:", error);
            }
            this.webSocket = null;
        }

        this.connecting = true;
        console.log("Setting up WebSocket connection to:", this.proxyUrl);

        try {
            this.webSocket = new WebSocket(this.proxyUrl);

            this.webSocket.onopen = (event) => {
                console.log("WebSocket connection opened");
                this.connecting = false;
                this.retryCount = 0;
                this.sendInitialSetupMessages();
                this.onConnectionStarted();
            };

            this.webSocket.onclose = (event) => {
                console.log("WebSocket connection closed:", event);
                this.connecting = false;

                if (event.code !== 1000 && this.retryCount < this.maxRetries) {
                    console.log(`Retrying connection (${this.retryCount + 1}/${this.maxRetries})`);
                    this.retryCount++;
                    setTimeout(() => this.setupWebSocketToService(), this.retryDelay);
                } else if (event.code !== 1000) {
                    this.onErrorMessage(`Connection closed: ${event.reason || 'Unknown reason'}`);
                }
            };

            this.webSocket.onerror = (event) => {
                console.error("WebSocket error:", event);
                this.connecting = false;
                this.onErrorMessage("Connection error occurred");
            };

            this.webSocket.onmessage = this.onReceiveMessage.bind(this);
        } catch (error) {
            console.error("Error creating WebSocket:", error);
            this.connecting = false;
            this.onErrorMessage("Failed to create connection: " + error.message);
        }
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
