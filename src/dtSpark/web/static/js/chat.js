/**
 * Chat interface JavaScript for Spark web interface
 *
 * Handles chat message display, history loading, and UI interactions
 */

/**
 * Load chat history for a conversation
 * @param {number} conversationId - The conversation ID
 */
async function loadChatHistory(conversationId) {
    try {
        const response = await fetch(`/api/chat/${conversationId}/history`);
        const data = await response.json();

        const messagesContainer = document.getElementById('chat-messages');
        messagesContainer.innerHTML = '';

        if (data.messages.length === 0) {
            messagesContainer.innerHTML = `
                <div class="text-center text-muted">
                    <i class="bi bi-chat"></i>
                    <p class="mt-2">No messages yet. Start the conversation!</p>
                </div>
            `;
            return;
        }

        data.messages.forEach(message => {
            appendMessage(message.role, message.content, message.timestamp);
        });

        // Scroll to bottom
        scrollToBottom();

    } catch (error) {
        console.error('Error loading chat history:', error);
        document.getElementById('chat-messages').innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle-fill"></i> Failed to load chat history
            </div>
        `;
    }
}

/**
 * Append a message to the chat
 * @param {string} role - Message role ('user' or 'assistant')
 * @param {string} content - Message content
 * @param {string} timestamp - Message timestamp (optional)
 */
function appendMessage(role, content, timestamp = null) {
    // Check if content contains tool results
    if (content.startsWith('[TOOL_RESULTS]')) {
        appendToolResults(content, timestamp);
        return;
    }

    // Check if content contains tool calls (JSON with tool_use blocks)
    if (role === 'assistant' && content.trim().startsWith('[')) {
        try {
            const blocks = JSON.parse(content);
            if (Array.isArray(blocks)) {
                // Check if this contains tool_use blocks
                const hasToolUse = blocks.some(block => block.type === 'tool_use');
                if (hasToolUse) {
                    // Display tool calls and text separately
                    blocks.forEach(block => {
                        if (block.type === 'text' && block.text) {
                            // Display text content normally
                            appendRegularMessage('assistant', block.text, timestamp);
                        } else if (block.type === 'tool_use') {
                            // Display tool call
                            appendToolCall(block.name, block.input);
                        }
                    });
                    return;
                }
            }
        } catch (e) {
            // Not JSON or not the expected format, fall through to regular display
        }
    }

    // Check if this is a rollup summary
    if (content.startsWith('[Summary of previous conversation]')) {
        appendRollupSummary(content, timestamp);
        return;
    }

    // Regular message display
    appendRegularMessage(role, content, timestamp);
}

/**
 * Append a regular message (no special formatting)
 * @param {string} role - Message role
 * @param {string} content - Message content
 * @param {string} timestamp - Message timestamp (optional)
 */
function appendRegularMessage(role, content, timestamp = null) {
    const messagesContainer = document.getElementById('chat-messages');

    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${role}`;

    // Generate unique ID for the copy button
    const copyBtnId = 'copy-btn-' + Date.now() + '-' + Math.random().toString(36).substring(2, 11);

    // Create message header with copy icon
    const header = document.createElement('div');
    header.className = 'message-header d-flex justify-content-between align-items-center';
    header.innerHTML = `
        <div>
            <i class="bi bi-${role === 'user' ? 'person-fill' : 'robot'}"></i>
            <strong>${role === 'user' ? 'You' : 'Assistant'}</strong>
            ${timestamp ? `<span class="ms-2 text-muted small">${formatTimestamp(timestamp)}</span>` : ''}
        </div>
        <button id="${copyBtnId}" class="btn btn-link btn-sm p-0 copy-icon-btn" title="Copy to clipboard">
            <i class="bi bi-clipboard"></i>
        </button>
    `;

    // Create message content
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content markdown-content';

    if (role === 'assistant') {
        // Render markdown for assistant messages
        contentDiv.innerHTML = marked.parse(content);
    } else {
        // Plain text for user messages
        contentDiv.textContent = content;
    }

    messageDiv.appendChild(header);
    messageDiv.appendChild(contentDiv);
    messagesContainer.appendChild(messageDiv);

    // Add click handler for copy button after element is in DOM
    const copyBtn = document.getElementById(copyBtnId);
    if (copyBtn) {
        copyBtn.onclick = () => copyMessageToClipboard(content, copyBtn);
    }

    // Render mermaid diagrams if present (async, non-blocking)
    if (role === 'assistant' && typeof renderMermaidDiagrams === 'function') {
        renderMermaidDiagrams(contentDiv);
    }

    // Scroll to bottom
    scrollToBottom();
}

/**
 * Append tool results from [TOOL_RESULTS] content
 * @param {string} content - Content starting with [TOOL_RESULTS]
 * @param {string} timestamp - Message timestamp (optional)
 */
function appendToolResults(content, timestamp = null) {
    const messagesContainer = document.getElementById('chat-messages');

    try {
        // Parse the JSON after the [TOOL_RESULTS] marker
        const jsonContent = content.replace('[TOOL_RESULTS]', '').trim();
        const results = JSON.parse(jsonContent);

        if (Array.isArray(results)) {
            results.forEach((result, index) => {
                const resultDiv = document.createElement('div');
                resultDiv.className = 'tool-result';

                const toolId = result.tool_use_id || 'unknown';
                const resultContent = result.content || JSON.stringify(result);

                resultDiv.innerHTML = `
                    <div class="small">
                        <strong><i class="bi bi-check-circle-fill"></i> Tool Result ${index + 1}:</strong>
                        <code>${escapeHtml(toolId)}</code>
                        ${timestamp ? `<span class="ms-2">${formatTimestamp(timestamp)}</span>` : ''}
                    </div>
                    <pre class="small mb-0 mt-1">${escapeHtml(typeof resultContent === 'string' ? resultContent : JSON.stringify(resultContent, null, 2))}</pre>
                `;

                messagesContainer.appendChild(resultDiv);
            });
        }
    } catch (e) {
        console.error('Error parsing tool results:', e);
        // Fall back to displaying the raw content
        const resultDiv = document.createElement('div');
        resultDiv.className = 'tool-result';
        resultDiv.innerHTML = `
            <div class="small"><strong><i class="bi bi-check-circle-fill"></i> Tool Results</strong></div>
            <pre class="small mb-0 mt-1">${escapeHtml(content)}</pre>
        `;
        messagesContainer.appendChild(resultDiv);
    }

    scrollToBottom();
}

/**
 * Append a rollup summary message
 * @param {string} content - Rollup summary content
 * @param {string} timestamp - Message timestamp (optional)
 */
function appendRollupSummary(content, timestamp = null) {
    const messagesContainer = document.getElementById('chat-messages');

    const summaryDiv = document.createElement('div');
    summaryDiv.className = 'chat-message rollup-summary';
    summaryDiv.innerHTML = `
        <div class="message-header">
            <i class="bi bi-archive-fill"></i>
            <strong>Rollup Summary</strong>
            ${timestamp ? `<span class="ms-2">${formatTimestamp(timestamp)}</span>` : ''}
        </div>
        <div class="message-content markdown-content">
            ${marked.parse(content.replace('[Summary of previous conversation]', '').trim())}
        </div>
    `;

    messagesContainer.appendChild(summaryDiv);
    scrollToBottom();
}

/**
 * Append a tool call message
 * @param {string} toolName - Tool name
 * @param {object} toolInput - Tool input parameters
 */
function appendToolCall(toolName, toolInput) {
    const messagesContainer = document.getElementById('chat-messages');

    const toolDiv = document.createElement('div');
    toolDiv.className = 'tool-call';
    toolDiv.innerHTML = `
        <div class="small">
            <strong><i class="bi bi-tools"></i> Tool Call:</strong> <code>${escapeHtml(toolName)}</code>
        </div>
        <pre class="small mb-0 mt-1">${escapeHtml(JSON.stringify(toolInput, null, 2))}</pre>
    `;

    messagesContainer.appendChild(toolDiv);
    scrollToBottom();
}

/**
 * Append a tool result message
 * @param {string} toolName - Tool name
 * @param {object} toolResult - Tool result data
 */
function appendToolResult(toolName, toolResult) {
    const messagesContainer = document.getElementById('chat-messages');

    const resultDiv = document.createElement('div');
    resultDiv.className = 'tool-result';
    resultDiv.innerHTML = `
        <div class="small">
            <strong><i class="bi bi-check-circle-fill"></i> Tool Result:</strong> <code>${escapeHtml(toolName)}</code>
        </div>
        <pre class="small mb-0 mt-1">${escapeHtml(JSON.stringify(toolResult, null, 2))}</pre>
    `;

    messagesContainer.appendChild(resultDiv);
    scrollToBottom();
}

/**
 * Append a status message (e.g., "Processing...", "Generating response...")
 * @param {string} message - Status message
 * @param {string} id - Optional ID for the status element (for later removal)
 * @returns {HTMLElement} The created status element
 */
function appendStatus(message, id = null) {
    const messagesContainer = document.getElementById('chat-messages');

    const statusDiv = document.createElement('div');
    statusDiv.className = 'chat-message system';
    statusDiv.style.display = 'flex';
    statusDiv.style.alignItems = 'center';
    statusDiv.style.justifyContent = 'center';
    if (id) {
        statusDiv.id = id;
    }
    statusDiv.innerHTML = `
        <div class="spinner-border spinner-border-sm me-2" role="status">
            <span class="visually-hidden">Loading...</span>
        </div>
        <span>${escapeHtml(message)}</span>
    `;

    messagesContainer.appendChild(statusDiv);
    scrollToBottom();

    return statusDiv;
}

/**
 * Remove a status message
 * @param {string|HTMLElement} idOrElement - Status ID or element
 */
function removeStatus(idOrElement) {
    const element = typeof idOrElement === 'string' ?
        document.getElementById(idOrElement) :
        idOrElement;

    if (element?.parentNode) {
        element.remove();
    }
}

/**
 * Scroll chat messages to bottom
 */
function scrollToBottom() {
    const messagesContainer = document.getElementById('chat-messages');
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

/**
 * Clear all messages
 */
function clearMessages() {
    document.getElementById('chat-messages').innerHTML = '';
}

/**
 * Show typing indicator
 * @returns {HTMLElement} The typing indicator element
 */
function showTypingIndicator() {
    return appendStatus('', 'typing-indicator');
}

/**
 * Hide typing indicator
 */
function hideTypingIndicator() {
    removeStatus('typing-indicator');
}

/**
 * Update an assistant message with streaming content
 * @param {string} content - The content to append
 * @param {HTMLElement} messageElement - The message element to update (optional)
 * @returns {HTMLElement} The message element
 */
function updateStreamingMessage(content, messageElement = null) {
    console.log('updateStreamingMessage called with content:', content, 'messageElement:', messageElement);

    if (!messageElement) {
        // Create new message element with copy button
        console.log('Creating new message element');
        const messagesContainer = document.getElementById('chat-messages');
        messageElement = document.createElement('div');
        messageElement.className = 'chat-message assistant';

        // Generate unique ID for the copy button
        const copyBtnId = 'stream-copy-btn-' + Date.now() + '-' + Math.random().toString(36).substring(2, 11);

        messageElement.innerHTML = `
            <div class="message-header d-flex justify-content-between align-items-center">
                <div>
                    <i class="bi bi-robot"></i>
                    <strong>Assistant</strong>
                </div>
                <button id="${copyBtnId}" class="btn btn-link btn-sm p-0 copy-icon-btn" title="Copy to clipboard">
                    <i class="bi bi-clipboard"></i>
                </button>
            </div>
            <div class="message-content markdown-content"></div>
        `;
        messagesContainer.appendChild(messageElement);

        // Store content reference for copy functionality
        messageElement.dataset.rawContent = content;

        console.log('Message element created and appended');
    } else {
        // Update stored content for copy functionality
        messageElement.dataset.rawContent = content;
    }

    // Update content
    const contentDiv = messageElement.querySelector('.message-content');
    console.log('Parsing content with marked');
    try {
        contentDiv.innerHTML = marked.parse(content);
        console.log('Content updated, innerHTML:', contentDiv.innerHTML);
    } catch (error) {
        console.error('Error parsing markdown:', error);
        // Fallback to plain text
        contentDiv.textContent = content;
    }

    // Update copy button handler with latest content
    const copyBtn = messageElement.querySelector('.copy-icon-btn');
    if (copyBtn) {
        copyBtn.onclick = () => copyMessageToClipboard(messageElement.dataset.rawContent, copyBtn);
    }

    // Render mermaid diagrams if present (async, non-blocking)
    if (typeof renderMermaidDiagrams === 'function') {
        renderMermaidDiagrams(contentDiv);
    }

    scrollToBottom();

    return messageElement;
}

/**
 * Format timestamp for display
 * @param {string} timestamp - ISO timestamp string
 * @returns {string} Formatted timestamp
 */
function formatTimestamp(timestamp) {
    try {
        const date = new Date(timestamp);
        return date.toLocaleString();
    } catch (e) {
        return timestamp;
    }
}

/**
 * Escape HTML to prevent XSS
 * @param {string} unsafe - Unsafe string
 * @returns {string} Escaped string
 */
function escapeHtml(unsafe) {
    if (typeof unsafe !== 'string') {
        return unsafe;
    }
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/**
 * Show toast notification
 * @param {string} message - Toast message
 * @param {string} type - Toast type ('info', 'success', 'error', 'warning')
 */
function showToast(message, type = 'info') {
    // Check if toast container exists, create if not
    let toastContainer = document.querySelector('.toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        document.body.appendChild(toastContainer);
    }

    // Create toast element
    const toastId = 'toast-' + Date.now();
    const toast = document.createElement('div');
    toast.id = toastId;
    toast.className = 'toast';
    toast.role = 'alert';

    let bgClass = 'bg-primary';
    if (type === 'success') bgClass = 'bg-success';
    else if (type === 'error') bgClass = 'bg-danger';
    else if (type === 'warning') bgClass = 'bg-warning';

    toast.innerHTML = `
        <div class="toast-header ${bgClass} text-white">
            <strong class="me-auto">Notification</strong>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast"></button>
        </div>
        <div class="toast-body">${escapeHtml(message)}</div>
    `;

    toastContainer.appendChild(toast);

    // Show toast
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();

    // Remove from DOM after hidden
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}

/**
 * Show tool permission dialog and handle user response
 * @param {string} requestId - The permission request ID
 * @param {string} toolName - The tool name
 * @param {string} toolDescription - Optional tool description
 */
async function showToolPermissionDialog(requestId, toolName, toolDescription) {
    // Create modal HTML
    const modalHtml = `
        <div class="modal fade" id="toolPermissionModal" tabindex="-1" data-bs-backdrop="static" data-bs-keyboard="false">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header bg-warning text-dark">
                        <h5 class="modal-title">
                            <i class="bi bi-shield-lock-fill"></i> Tool Permission Request
                        </h5>
                    </div>
                    <div class="modal-body">
                        <p class="mb-3">
                            The assistant wants to use the tool: <strong>${escapeHtml(toolName)}</strong>
                        </p>
                        ${toolDescription ? `<p class="text-muted small mb-3">${escapeHtml(toolDescription)}</p>` : ''}
                        <p class="mb-2"><strong>Please choose an option:</strong></p>
                        <div class="d-grid gap-2">
                            <button type="button" class="btn btn-success permission-btn" data-response="once">
                                <i class="bi bi-play-circle"></i> Allow once - Run this time only
                            </button>
                            <button type="button" class="btn btn-primary permission-btn" data-response="allowed">
                                <i class="bi bi-check-circle"></i> Allow always - Run this time and all future times
                            </button>
                            <button type="button" class="btn btn-danger permission-btn" data-response="denied">
                                <i class="bi bi-x-circle"></i> Deny - Don't run this time or in the future
                            </button>
                            <button type="button" class="btn btn-secondary permission-btn" data-response="cancel">
                                <i class="bi bi-ban"></i> Cancel
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Remove existing modal if present
    const existingModal = document.getElementById('toolPermissionModal');
    if (existingModal) {
        existingModal.remove();
    }

    // Add modal to DOM
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Get modal element
    const modalElement = document.getElementById('toolPermissionModal');
    const modal = new bootstrap.Modal(modalElement);

    // Add click handlers to buttons
    const buttons = modalElement.querySelectorAll('.permission-btn');
    buttons.forEach(button => {
        button.addEventListener('click', async () => {
            const response = button.dataset.response;

            // Send response to server
            try {
                const formData = new FormData();
                formData.append('request_id', requestId);
                formData.append('response', response);

                const result = await fetch('/api/chat/permission/respond', {
                    method: 'POST',
                    body: formData
                });

                if (!result.ok) {
                    console.error('Failed to submit permission response:', result.statusText);
                    showToast('Failed to submit permission response', 'error');
                }
            } catch (error) {
                console.error('Error submitting permission response:', error);
                showToast('Error submitting permission response', 'error');
            }

            // Close modal
            modal.hide();
        });
    });

    // Clean up modal after it's hidden
    modalElement.addEventListener('hidden.bs.modal', () => {
        modalElement.remove();
    });

    // Show modal
    modal.show();
}

/**
 * Copy message content to clipboard
 * @param {string} content - The message content to copy
 * @param {HTMLElement} button - The copy button element
 */
function copyMessageToClipboard(content, button) {
    // Use the Clipboard API
    navigator.clipboard.writeText(content).then(() => {
        // Success - update icon temporarily
        const icon = button.querySelector('i');
        if (icon) {
            icon.className = 'bi bi-check-circle-fill text-success';

            // Reset icon after 2 seconds
            setTimeout(() => {
                icon.className = 'bi bi-clipboard';
            }, 2000);
        }

        // Show toast notification
        showToast('Message copied to clipboard', 'success');
    }).catch(err => {
        console.error('Failed to copy message:', err);
        showToast('Failed to copy message', 'error');
    });
}
