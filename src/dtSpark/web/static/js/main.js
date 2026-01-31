/**
 * Main JavaScript utilities for Spark web interface
 *
 * Provides common functions used across all pages
 */

// =============================================================================
// MARKDOWN, CODE HIGHLIGHTING, AND MERMAID CONFIGURATION
// =============================================================================

/**
 * Initialise Mermaid.js with dark theme
 */
if (typeof mermaid !== 'undefined') {
    mermaid.initialize({
        startOnLoad: false,  // We'll manually trigger rendering
        theme: 'dark',
        themeVariables: {
            primaryColor: '#3b82f6',
            primaryTextColor: '#e0e0e0',
            primaryBorderColor: '#404040',
            lineColor: '#606060',
            secondaryColor: '#1e3a5f',
            tertiaryColor: '#2a2a2a',
            background: '#1a1a1a',
            mainBkg: '#2a2a2a',
            nodeBorder: '#404040',
            clusterBkg: '#2a2a2a',
            clusterBorder: '#404040',
            titleColor: '#e0e0e0',
            edgeLabelBackground: '#2a2a2a',
        },
        flowchart: {
            useMaxWidth: true,
            htmlLabels: true,
            curve: 'basis'
        },
        sequence: {
            useMaxWidth: true,
            diagramMarginX: 50,
            diagramMarginY: 10,
            actorMargin: 50,
            width: 150,
            height: 65,
            boxMargin: 10,
            boxTextMargin: 5,
            noteMargin: 10,
            messageMargin: 35
        }
    });
}

/**
 * Configure Marked.js with highlight.js for code blocks
 */
if (typeof marked !== 'undefined') {
    // Create custom renderer for code blocks
    const renderer = new marked.Renderer();

    // Override code block rendering
    // Note: marked.js v5+ passes a token object instead of separate parameters
    renderer.code = function(tokenOrCode, language) {
        // Handle both old API (code, language) and new API (token object)
        let code, lang;
        if (typeof tokenOrCode === 'object' && tokenOrCode !== null) {
            // New marked.js API (v5+): receives token object
            code = tokenOrCode.text || '';
            lang = tokenOrCode.lang || '';
        } else {
            // Old marked.js API: receives separate parameters
            code = tokenOrCode || '';
            lang = language || '';
        }

        // Handle mermaid diagrams
        if (lang === 'mermaid') {
            const id = 'mermaid-' + Math.random().toString(36).substring(2, 11);
            return `<div class="mermaid-container"><pre class="mermaid" id="${id}">${escapeHtmlForMermaid(code)}</pre></div>`;
        }

        // Use highlight.js for other code blocks
        if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
            try {
                const highlighted = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
                return `<pre><code class="hljs language-${lang}">${highlighted}</code></pre>`;
            } catch (e) {
                console.warn('Highlight.js error:', e);
            }
        }

        // Fallback: auto-detect language or plain text
        if (typeof hljs !== 'undefined' && code) {
            try {
                const highlighted = hljs.highlightAuto(code).value;
                return `<pre><code class="hljs">${highlighted}</code></pre>`;
            } catch (e) {
                console.warn('Highlight.js auto-detect error:', e);
            }
        }

        // Final fallback: plain code block
        return `<pre><code>${escapeHtml(code)}</code></pre>`;
    };

    // Configure marked options
    marked.setOptions({
        renderer: renderer,
        gfm: true,           // GitHub Flavoured Markdown
        breaks: true,        // Convert \n to <br>
        pedantic: false,
        smartLists: true,
        smartypants: false,
    });
}

/**
 * Escape HTML for mermaid (preserve diagram syntax)
 * @param {string} text - Text to escape
 * @returns {string} Escaped text safe for mermaid
 */
function escapeHtmlForMermaid(text) {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/**
 * Copy SVG element to clipboard as PNG image
 * @param {SVGElement} svgElement - The SVG element to copy
 * @param {HTMLElement} button - The button element (for feedback)
 */
async function copySvgToClipboard(svgElement, button) {
    try {
        // Get SVG dimensions
        const svgRect = svgElement.getBoundingClientRect();
        const width = Math.ceil(svgRect.width) || 800;
        const height = Math.ceil(svgRect.height) || 600;

        // Clone SVG and prepare for rendering
        const svgClone = svgElement.cloneNode(true);

        // Set explicit dimensions and viewBox
        svgClone.setAttribute('width', width);
        svgClone.setAttribute('height', height);
        if (!svgClone.getAttribute('viewBox')) {
            svgClone.setAttribute('viewBox', `0 0 ${width} ${height}`);
        }

        // Add xmlns if missing (required for data URL)
        if (!svgClone.getAttribute('xmlns')) {
            svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        }

        // Add dark background for better visibility
        const bgRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        bgRect.setAttribute('width', '100%');
        bgRect.setAttribute('height', '100%');
        bgRect.setAttribute('fill', '#1a1a1a');
        svgClone.prepend(bgRect);

        // Serialise SVG to string
        const serializer = new XMLSerializer();
        let svgString = serializer.serializeToString(svgClone);

        // Encode SVG as base64 data URL (avoids tainted canvas issues)
        const base64Svg = btoa(unescape(encodeURIComponent(svgString)));
        const dataUrl = 'data:image/svg+xml;base64,' + base64Svg;

        // Create canvas and draw image
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        const img = new Image();

        // Set up promise-based loading
        await new Promise((resolve, reject) => {
            img.onload = () => {
                // Set canvas size with scale for better quality
                const scale = 2;
                canvas.width = width * scale;
                canvas.height = height * scale;
                ctx.scale(scale, scale);

                // Draw image on canvas
                ctx.drawImage(img, 0, 0, width, height);
                resolve();
            };

            img.onerror = (e) => {
                reject(new Error('Failed to load SVG image'));
            };

            img.src = dataUrl;
        });

        // Convert to blob and copy to clipboard
        const blob = await new Promise((resolve) => {
            canvas.toBlob(resolve, 'image/png');
        });

        if (!blob) {
            throw new Error('Failed to create image blob');
        }

        try {
            await navigator.clipboard.write([
                new ClipboardItem({ 'image/png': blob })
            ]);

            // Show success feedback
            if (button) {
                const icon = button.querySelector('i');
                if (icon) {
                    icon.className = 'bi bi-check-circle-fill text-success';
                    setTimeout(() => {
                        icon.className = 'bi bi-clipboard';
                    }, 2000);
                }
            }
            showToast('Diagram copied to clipboard', 'success');
        } catch (clipboardError) {
            console.error('Clipboard write failed:', clipboardError);
            // Fallback: offer download
            downloadDiagramAsPng(canvas, 'diagram.png');
            showToast('Clipboard not available - downloading image instead', 'info');
        }

    } catch (e) {
        console.error('Error copying diagram:', e);
        showToast('Failed to copy diagram: ' + e.message, 'error');
    }
}

/**
 * Download canvas as PNG file (fallback when clipboard not available)
 * @param {HTMLCanvasElement} canvas - Canvas element
 * @param {string} filename - Download filename
 */
function downloadDiagramAsPng(canvas, filename) {
    const link = document.createElement('a');
    link.download = filename;
    link.href = canvas.toDataURL('image/png');
    link.click();
}

/**
 * Render all mermaid diagrams in a container
 * @param {HTMLElement} container - Container element to search for mermaid blocks
 */
async function renderMermaidDiagrams(container) {
    if (typeof mermaid === 'undefined') return;

    const mermaidBlocks = container.querySelectorAll('pre.mermaid');
    if (mermaidBlocks.length === 0) return;

    for (const block of mermaidBlocks) {
        try {
            const id = block.id || 'mermaid-' + Math.random().toString(36).substring(2, 11);
            const code = block.textContent;

            // Render the diagram
            const { svg } = await mermaid.render(id + '-svg', code);

            // Create wrapper with copy button
            const wrapper = document.createElement('div');
            wrapper.className = 'mermaid-diagram';

            // Add copy button
            const copyBtn = document.createElement('button');
            copyBtn.className = 'diagram-copy-btn btn btn-sm';
            copyBtn.title = 'Copy diagram to clipboard';
            copyBtn.innerHTML = '<i class="bi bi-clipboard"></i>';

            // Add SVG content
            const svgContainer = document.createElement('div');
            svgContainer.className = 'mermaid-svg-container';
            svgContainer.innerHTML = svg;

            wrapper.appendChild(copyBtn);
            wrapper.appendChild(svgContainer);

            // Add click handler for copy button
            copyBtn.onclick = () => {
                const svgElement = svgContainer.querySelector('svg');
                if (svgElement) {
                    copySvgToClipboard(svgElement, copyBtn);
                }
            };

            block.replaceWith(wrapper);
        } catch (e) {
            console.error('Mermaid rendering error:', e);
            // Show error message in the block
            block.classList.add('mermaid-error');
            block.innerHTML = `<span class="text-danger">Diagram rendering error: ${escapeHtml(e.message || 'Unknown error')}</span>\n\n${block.textContent}`;
        }
    }
}

/**
 * Parse markdown and render with syntax highlighting and mermaid support
 * @param {string} content - Markdown content to parse
 * @param {HTMLElement} targetElement - Element to render into
 */
async function renderMarkdown(content, targetElement) {
    if (typeof marked === 'undefined') {
        targetElement.textContent = content;
        return;
    }

    // Parse markdown
    targetElement.innerHTML = marked.parse(content);

    // Render mermaid diagrams
    await renderMermaidDiagrams(targetElement);
}

// =============================================================================
// GENERAL UTILITIES
// =============================================================================

/**
 * Format a timestamp to local date/time string
 * @param {string|Date} timestamp - The timestamp to format
 * @returns {string} Formatted date/time string
 */
function formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleString();
}

/**
 * Format a number with thousands separators
 * @param {number} num - The number to format
 * @returns {string} Formatted number string
 */
function formatNumber(num) {
    return num.toLocaleString();
}

/**
 * Truncate text to a maximum length
 * @param {string} text - The text to truncate
 * @param {number} maxLength - Maximum length
 * @returns {string} Truncated text with ellipsis if needed
 */
function truncateText(text, maxLength = 100) {
    if (text.length <= maxLength) {
        return text;
    }
    return text.substring(0, maxLength) + '...';
}

/**
 * Show a toast notification
 * @param {string} message - The message to display
 * @param {string} type - Toast type (success, error, warning, info)
 */
function showToast(message, type = 'info') {
    // Create toast container if it doesn't exist
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'position-fixed bottom-0 end-0 p-3';
        container.style.zIndex = '11';
        document.body.appendChild(container);
    }

    // Create toast
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type === 'error' ? 'danger' : type} border-0`;
    toast.role = 'alert';
    toast.ariaLive = 'assertive';
    toast.ariaAtomic = 'true';

    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;

    container.appendChild(toast);

    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();

    // Remove toast element after it's hidden
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}

/**
 * Escape HTML to prevent XSS
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Copy text to clipboard
 * @param {string} text - Text to copy
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('Copied to clipboard', 'success');
    } catch (err) {
        showToast('Failed to copy to clipboard', 'error');
    }
}

/**
 * Download text as a file
 * @param {string} content - File content
 * @param {string} filename - File name
 * @param {string} mimeType - MIME type
 */
function downloadFile(content, filename, mimeType = 'text/plain') {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

/**
 * Make an API request with error handling
 * @param {string} url - API endpoint URL
 * @param {object} options - Fetch options
 * @returns {Promise<any>} Response data
 */
async function apiRequest(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        console.error('API request failed:', error);
        throw error;
    }
}

/**
 * Debounce function to limit function call frequency
 * @param {Function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @returns {Function} Debounced function
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Format file size to human-readable string
 * @param {number} bytes - File size in bytes
 * @returns {string} Formatted file size
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}
