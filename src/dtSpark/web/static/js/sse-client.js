/**
 * Server-Sent Events (SSE) client for Spark web interface
 *
 * Handles real-time streaming of chat responses via SSE
 */

/**
 * Send a message and handle streaming response via SSE
 * @param {number} conversationId - The conversation ID
 * @param {string} message - The message to send
 * @param {boolean} webSearchActive - Whether web search should be used for this request
 */
async function sendMessageWithSSE(conversationId, message, webSearchActive = false) {
    // Show typing indicator
    let typingIndicator = showTypingIndicator();

    // Track streaming message element
    let streamingMessageElement = null;
    let accumulatedContent = '';

    return new Promise((resolve) => {
        try {
            // Create EventSource for SSE
            const encodedMessage = encodeURIComponent(message);
            let url = `/api/stream/chat?message=${encodedMessage}&conversation_id=${conversationId}`;
            if (webSearchActive) {
                url += '&web_search_active=true';
            }
            const eventSource = new EventSource(url);

            // Handle different event types
            eventSource.addEventListener('status', (event) => {
                const data = JSON.parse(event.data);
                console.log('Status:', data);

                // Update typing indicator with status
                if (typingIndicator && typingIndicator.parentNode) {
                    const statusText = data.message || '';
                    typingIndicator.querySelector('.visually-hidden').nextSibling.textContent = statusText;
                }
            });

            eventSource.addEventListener('response', (event) => {
                const data = JSON.parse(event.data);
                console.log('Received response event:', data);

                // Hide typing indicator on first response
                if (typingIndicator && typingIndicator.parentNode) {
                    console.log('Hiding typing indicator');
                    hideTypingIndicator();
                    typingIndicator = null;  // Clear reference after hiding
                }

                if (data.type === 'text') {
                    if (data.final) {
                        // Final response - this is the main assistant response after tool execution
                        console.log('Final response received, content length:', data.content ? data.content.length : 0);
                        accumulatedContent += data.content;
                        console.log('Accumulated content:', accumulatedContent);

                        // Ensure we have content before displaying
                        if (accumulatedContent.trim().length > 0) {
                            streamingMessageElement = updateStreamingMessage(
                                accumulatedContent,
                                streamingMessageElement
                            );
                            console.log('Updated streaming message element:', streamingMessageElement);
                        } else {
                            console.warn('No content to display');
                        }
                        eventSource.close();
                        resolve();
                    } else {
                        // Non-final response - text that appears with tool calls
                        // Display immediately as a separate message
                        console.log('Non-final response, appending:', data.content);
                        appendMessage('assistant', data.content);
                    }
                }
            });

            eventSource.addEventListener('tool_start', (event) => {
                const data = JSON.parse(event.data);
                appendToolCall(data.tool_name, data.input);
            });

            eventSource.addEventListener('tool_complete', (event) => {
                const data = JSON.parse(event.data);
                // Display tool result
                appendToolResult(data.tool_use_id, { content: data.content });
            });

            eventSource.addEventListener('tool_error', (event) => {
                const data = JSON.parse(event.data);
                appendToolResult(data.tool_name, { error: data.error });
            });

            eventSource.addEventListener('web_search_start', (event) => {
                const data = JSON.parse(event.data);
                console.log('Web search starting:', data);
                appendWebSearchStart(data.tool_use_id, data.input);
            });

            eventSource.addEventListener('web_search_results', (event) => {
                const data = JSON.parse(event.data);
                console.log('Web search results:', data);
                appendWebSearchResults(data.tool_use_id, data.sources, data.source_count);
            });

            eventSource.addEventListener('permission_request', (event) => {
                const data = JSON.parse(event.data);
                console.log('Permission request received:', data);

                // Show permission modal/dialog
                showToolPermissionDialog(data.request_id, data.tool_name, data.tool_description);
            });

            eventSource.addEventListener('progress', (event) => {
                const data = JSON.parse(event.data);
                // Update progress (if we want to show a progress bar)
                console.log('Progress:', data);
            });

            eventSource.addEventListener('complete', (event) => {
                // Stream complete
                console.log('Stream complete');
                eventSource.close();

                // Hide typing indicator if still visible
                if (typingIndicator && typingIndicator.parentNode) {
                    console.log('Hiding typing indicator on complete');
                    hideTypingIndicator();
                    typingIndicator = null;
                }

                resolve();
            });

            eventSource.addEventListener('error', (event) => {
                console.error('SSE error:', event);
                const data = JSON.parse(event.data);

                // Hide typing indicator
                if (typingIndicator && typingIndicator.parentNode) {
                    console.log('Hiding typing indicator on error');
                    hideTypingIndicator();
                    typingIndicator = null;
                }

                // Format detailed error message
                const errorContent = formatErrorMessage(data);
                appendMessage('error', errorContent);

                eventSource.close();
                resolve();
            });

            eventSource.onerror = (error) => {
                console.error('EventSource failed:', error);

                // Hide typing indicator
                if (typingIndicator && typingIndicator.parentNode) {
                    console.log('Hiding typing indicator on connection error');
                    hideTypingIndicator();
                    typingIndicator = null;
                }

                // If we haven't received any content, show error
                if (!streamingMessageElement) {
                    const errorContent = formatErrorMessage({
                        message: 'Connection lost to the server',
                        error_type: 'ConnectionError',
                        suggestion: 'Check your network connection and try again.'
                    });
                    appendMessage('error', errorContent);
                }

                eventSource.close();
                resolve();
            };

        } catch (error) {
            console.error('Error sending message:', error);

            // Hide typing indicator
            if (typingIndicator) {
                hideTypingIndicator();
            }

            showToast('Failed to send message', 'error');
            resolve();
        }
    });
}

/**
 * Alternative: Send message using traditional HTTP POST (fallback)
 * @param {number} conversationId - The conversation ID
 * @param {string} message - The message to send
 */
async function sendMessageHTTP(conversationId, message) {
    try {
        // Show typing indicator
        const typingIndicator = showTypingIndicator();

        // Create form data
        const formData = new FormData();
        formData.append('message', message);

        // Send request
        const response = await fetch(`/api/chat/${conversationId}/message`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error('Failed to send message');
        }

        const data = await response.json();

        // Hide typing indicator
        hideTypingIndicator();

        // Append response
        if (data.status === 'success' && data.response) {
            appendMessage('assistant', data.response);
        } else {
            appendMessage('system', 'No response from assistant');
        }

    } catch (error) {
        console.error('Error sending message:', error);
        hideTypingIndicator();
        showToast('Failed to send message', 'error');
    }
}

/**
 * Stream progress for a long-running task
 * @param {string} taskName - The task name
 * @param {number} totalSteps - Total number of steps
 * @param {Function} onProgress - Callback for progress updates
 */
async function streamProgress(taskName, totalSteps, onProgress) {
    try {
        const eventSource = new EventSource(
            `/api/stream/progress?task_name=${encodeURIComponent(taskName)}&total_steps=${totalSteps}`
        );

        eventSource.addEventListener('progress', (event) => {
            const data = JSON.parse(event.data);

            if (onProgress) {
                onProgress(data);
            }

            if (data.step >= data.total) {
                eventSource.close();
            }
        });

        eventSource.onerror = (error) => {
            console.error('Progress stream error:', error);
            eventSource.close();
        };

    } catch (error) {
        console.error('Error streaming progress:', error);
    }
}

/**
 * Format an error message with details and suggestion
 * @param {Object} data - Error data from SSE event
 * @returns {string} Formatted HTML for error display
 */
function formatErrorMessage(data) {
    const message = data.message || 'An unknown error occurred';
    const errorType = data.error_type || '';
    const errorCode = data.error_code || '';
    const suggestion = data.suggestion || '';
    const retries = data.retries_attempted || 0;

    let html = `<div class="error-details">`;

    // Main error message
    html += `<strong>${escapeHtml(message)}</strong>`;

    // Error type/code if available
    if (errorType && errorType !== 'Unknown') {
        html += `<div class="mt-2 small text-muted">`;
        if (errorCode && errorCode !== errorType) {
            html += `Error: ${escapeHtml(errorType)} (${escapeHtml(errorCode)})`;
        } else {
            html += `Error: ${escapeHtml(errorType)}`;
        }
        if (retries > 0) {
            html += ` &mdash; Failed after ${retries} retry attempt(s)`;
        }
        html += `</div>`;
    }

    html += `</div>`;

    // Suggestion if available
    if (suggestion) {
        html += `<div class="error-suggestion">`;
        html += `<i class="bi bi-lightbulb"></i>`;
        html += `<span>${escapeHtml(suggestion)}</span>`;
        html += `</div>`;
    }

    return html;
}

