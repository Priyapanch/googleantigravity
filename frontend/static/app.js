// Frontend JS logic connecting to FastAPI Agent Engine Proxy
let sessionId = null;
const messagesContainer = document.getElementById("chat-messages");
const chatForm = document.getElementById("chat-form");
const userInput = document.getElementById("user-input");
const sessionBadge = document.getElementById("session-badge");
const sendBtn = document.getElementById("send-btn");

// Fetch backend info on load
async function initInfo() {
  try {
    const res = await fetch("/api/info");
    const data = await res.json();
    console.log("Agent proxy backend info:", data);
  } catch (err) {
    console.warn("Could not fetch info:", err);
  }
}
initInfo();

function appendMessage(role, text) {
  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${role}`;
  
  const contentDiv = document.createElement("div");
  contentDiv.className = "message-content";
  
  if (role === "bot" && typeof marked !== "undefined") {
    contentDiv.innerHTML = marked.parse(text);
  } else {
    contentDiv.textContent = text;
  }
  
  msgDiv.appendChild(contentDiv);
  messagesContainer.appendChild(msgDiv);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
  return contentDiv;
}

function appendTypingIndicator() {
  const msgDiv = document.createElement("div");
  msgDiv.className = "message bot typing";
  
  const contentDiv = document.createElement("div");
  contentDiv.className = "message-content";
  contentDiv.innerHTML = `
    <div class="typing-dots">
      <span></span><span></span><span></span>
    </div>
  `;
  
  msgDiv.appendChild(contentDiv);
  messagesContainer.appendChild(msgDiv);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
  return msgDiv;
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = userInput.value.trim();
  if (!text) return;

  userInput.value = "";
  appendMessage("user", text);
  
  const typingIndicator = appendTypingIndicator();
  sendBtn.disabled = true;

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        session_id: sessionId,
      }),
    });

    if (!response.ok) {
      throw new Error(`Proxy error: ${response.statusText}`);
    }

    typingIndicator.remove();
    const botMsgDiv = appendMessage("bot", "");
    let botText = "";

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop() || "";

      for (const lineGroup of lines) {
        const eventLines = lineGroup.split("\n");
        let eventType = "message";
        let dataStr = "";

        for (const line of eventLines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            dataStr = line.slice(6).trim();
          }
        }

        if (eventType === "session_id" && dataStr) {
          try {
            const parsed = JSON.parse(dataStr);
            if (parsed.session_id) {
              sessionId = parsed.session_id;
              sessionBadge.textContent = `Session: ${sessionId.slice(-8)}`;
            }
          } catch (e) {}
        } else if (dataStr) {
          try {
            const parsed = JSON.parse(dataStr);
            if (parsed.content && parsed.content.parts) {
              for (const part of parsed.content.parts) {
                if (part.text) {
                  botText += part.text;
                }
              }
              if (typeof marked !== "undefined") {
                botMsgDiv.innerHTML = marked.parse(botText);
              } else {
                botMsgDiv.textContent = botText;
              }
              messagesContainer.scrollTop = messagesContainer.scrollHeight;
            }
          } catch (e) {
            // raw text fallback
            botText += dataStr;
            botMsgDiv.textContent = botText;
          }
        }
      }
    }
  } catch (err) {
    typingIndicator.remove();
    appendMessage("system", `Error: ${err.message}`);
  } finally {
    sendBtn.disabled = false;
  }
});
