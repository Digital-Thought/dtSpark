/**
 * Autonomous Actions JavaScript for Spark web interface
 *
 * Handles action management, runs viewing, and API interactions
 */

// Store for current context
let currentActionId = null;
let currentRunId = null;
let availableModels = [];
let availableTools = [];

// =============================================================================
// LOAD AND DISPLAY ACTIONS
// =============================================================================

/**
 * Load all actions from API
 */
async function loadActions() {
    const tbody = document.getElementById('actions-tbody');
    const includeDisabled = document.getElementById('showDisabled').checked;

    try {
        const response = await fetch(`/api/actions?include_disabled=${includeDisabled}`);
        if (!response.ok) throw new Error('Failed to load actions');

        const actions = await response.json();

        if (actions.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center text-muted py-4">
                        <i class="bi bi-inbox"></i> No actions found.
                        <button class="btn btn-link" onclick="showCreateModal()">Create your first action</button>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = actions.map(action => `
            <tr class="${!action.is_enabled ? 'table-secondary' : ''}">
                <td>${action.id}</td>
                <td>
                    <a href="#" onclick="viewAction(${action.id}); return false;">
                        ${escapeHtml(action.name)}
                    </a>
                </td>
                <td><small class="text-muted">${escapeHtml(action.model_id)}</small></td>
                <td>${formatSchedule(action)}</td>
                <td>
                    <span class="badge ${action.context_mode === 'cumulative' ? 'bg-info' : 'bg-secondary'}">
                        ${action.context_mode}
                    </span>
                </td>
                <td>
                    ${action.is_enabled
                        ? '<span class="badge bg-success">Enabled</span>'
                        : '<span class="badge bg-danger">Disabled</span>'}
                </td>
                <td>${action.last_run_at ? formatTimestamp(action.last_run_at) : '<span class="text-muted">Never</span>'}</td>
                <td>${formatFailures(action)}</td>
                <td>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-primary" onclick="runActionNow(${action.id})" title="Run now">
                            <i class="bi bi-play-fill"></i>
                        </button>
                        <button class="btn btn-outline-secondary" onclick="viewActionRuns(${action.id}, '${escapeHtml(action.name)}')" title="View runs">
                            <i class="bi bi-clock-history"></i>
                        </button>
                        <button class="btn btn-outline-secondary" onclick="editAction(${action.id})" title="Edit">
                            <i class="bi bi-pencil"></i>
                        </button>
                        ${action.is_enabled
                            ? `<button class="btn btn-outline-warning" onclick="disableAction(${action.id})" title="Disable">
                                <i class="bi bi-pause-fill"></i>
                               </button>`
                            : `<button class="btn btn-outline-success" onclick="enableAction(${action.id})" title="Enable">
                                <i class="bi bi-play"></i>
                               </button>`}
                        <button class="btn btn-outline-danger" onclick="confirmDeleteAction(${action.id}, '${escapeHtml(action.name)}')" title="Delete">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `).join('');

    } catch (error) {
        console.error('Error loading actions:', error);
        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="text-center text-danger py-4">
                    <i class="bi bi-exclamation-triangle"></i> Failed to load actions
                </td>
            </tr>
        `;
    }
}

/**
 * Load recent runs across all actions
 */
async function loadRecentRuns() {
    const tbody = document.getElementById('runs-tbody');

    try {
        const response = await fetch('/api/actions/runs/recent?limit=10');
        if (!response.ok) throw new Error('Failed to load recent runs');

        const runs = await response.json();

        if (runs.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center text-muted py-4">
                        <i class="bi bi-inbox"></i> No runs yet
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = runs.map(run => `
            <tr>
                <td>${run.id}</td>
                <td>${escapeHtml(run.action_name || 'Unknown')}</td>
                <td>${formatTimestamp(run.started_at)}</td>
                <td>${formatRunStatus(run.status)}</td>
                <td>${formatDuration(run.started_at, run.completed_at)}</td>
                <td>${formatTokens(run.input_tokens, run.output_tokens)}</td>
                <td>
                    <button class="btn btn-sm btn-outline-secondary" onclick="viewRunDetails(${run.action_id}, ${run.id})">
                        <i class="bi bi-eye"></i> View
                    </button>
                </td>
            </tr>
        `).join('');

    } catch (error) {
        console.error('Error loading recent runs:', error);
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center text-danger py-4">
                    <i class="bi bi-exclamation-triangle"></i> Failed to load recent runs
                </td>
            </tr>
        `;
    }
}

/**
 * Check for failed actions and show warning
 */
async function checkFailedActions() {
    try {
        const response = await fetch('/api/actions/status/failed-count');
        if (!response.ok) return;

        const data = await response.json();
        const warning = document.getElementById('failed-warning');
        const text = document.getElementById('failed-count-text');

        if (data.failed_count > 0) {
            text.textContent = `${data.failed_count} action(s) have been auto-disabled due to failures.`;
            warning.classList.remove('d-none');
        } else {
            warning.classList.add('d-none');
        }
    } catch (error) {
        console.error('Error checking failed actions:', error);
    }
}

// =============================================================================
// ACTION CRUD OPERATIONS
// =============================================================================

/**
 * Show create action modal
 */
function showCreateModal() {
    currentActionId = null;
    document.getElementById('actionModalTitle').textContent = 'Create Action';
    document.getElementById('actionForm').reset();
    document.getElementById('actionId').value = '';

    // Set default run date to tomorrow at 9am
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(9, 0, 0, 0);
    document.getElementById('runDate').value = tomorrow.toISOString().slice(0, 16);

    updateScheduleConfig();
    resetToolPermissions();

    const modal = new bootstrap.Modal(document.getElementById('actionModal'));
    modal.show();
}

/**
 * Edit an existing action
 */
async function editAction(actionId) {
    try {
        const response = await fetch(`/api/actions/${actionId}`);
        if (!response.ok) throw new Error('Failed to load action');

        const action = await response.json();
        currentActionId = actionId;

        document.getElementById('actionModalTitle').textContent = 'Edit Action';
        document.getElementById('actionId').value = actionId;
        document.getElementById('actionName').value = action.name;
        document.getElementById('actionDescription').value = action.description;
        document.getElementById('actionPrompt').value = action.action_prompt;
        document.getElementById('actionModel').value = action.model_id;
        document.getElementById('scheduleType').value = action.schedule_type;
        document.getElementById('contextMode').value = action.context_mode;
        document.getElementById('maxFailures').value = action.max_failures;

        updateScheduleConfig();

        // Set schedule config
        if (action.schedule_type === 'one_off' && action.schedule_config?.run_date) {
            document.getElementById('runDate').value = action.schedule_config.run_date.slice(0, 16);
        } else if (action.schedule_type === 'recurring' && action.schedule_config?.cron_expression) {
            document.getElementById('cronExpression').value = action.schedule_config.cron_expression;
        }

        // Set tool permissions
        setToolPermissions(action.tool_permissions || []);

        const modal = new bootstrap.Modal(document.getElementById('actionModal'));
        modal.show();

    } catch (error) {
        console.error('Error loading action:', error);
        showToast('Failed to load action', 'error');
    }
}

/**
 * Save action (create or update)
 */
async function saveAction() {
    const actionId = document.getElementById('actionId').value;
    const isEdit = !!actionId;

    // Gather form data
    const scheduleType = document.getElementById('scheduleType').value;
    let scheduleConfig = {};

    if (scheduleType === 'one_off') {
        const runDate = document.getElementById('runDate').value;
        if (!runDate) {
            showToast('Please select a run date', 'error');
            return;
        }
        scheduleConfig = { run_date: new Date(runDate).toISOString() };
    } else {
        const cronExpr = document.getElementById('cronExpression').value.trim();
        if (!cronExpr) {
            showToast('Please enter a cron expression', 'error');
            return;
        }
        scheduleConfig = { cron_expression: cronExpr };
    }

    const data = {
        name: document.getElementById('actionName').value.trim(),
        description: document.getElementById('actionDescription').value.trim(),
        action_prompt: document.getElementById('actionPrompt').value.trim(),
        model_id: document.getElementById('actionModel').value,
        schedule_type: scheduleType,
        schedule_config: scheduleConfig,
        context_mode: document.getElementById('contextMode').value,
        max_failures: parseInt(document.getElementById('maxFailures').value),
        tool_permissions: getToolPermissions()
    };

    // Validate required fields
    if (!data.name || !data.description || !data.action_prompt || !data.model_id) {
        showToast('Please fill in all required fields', 'error');
        return;
    }

    try {
        const url = isEdit ? `/api/actions/${actionId}` : '/api/actions';
        const method = isEdit ? 'PUT' : 'POST';

        const response = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to save action');
        }

        showToast(isEdit ? 'Action updated successfully' : 'Action created successfully', 'success');

        // Close modal and reload
        bootstrap.Modal.getInstance(document.getElementById('actionModal')).hide();
        loadActions();
        checkFailedActions();

    } catch (error) {
        console.error('Error saving action:', error);
        showToast(error.message, 'error');
    }
}

/**
 * View action details
 */
async function viewAction(actionId) {
    try {
        const response = await fetch(`/api/actions/${actionId}`);
        if (!response.ok) throw new Error('Failed to load action');

        const action = await response.json();

        const body = document.getElementById('viewActionBody');
        body.innerHTML = `
            <div class="row">
                <div class="col-md-6">
                    <h6>Name</h6>
                    <p>${escapeHtml(action.name)}</p>

                    <h6>Description</h6>
                    <p>${escapeHtml(action.description)}</p>

                    <h6>Model</h6>
                    <p><code>${escapeHtml(action.model_id)}</code></p>

                    <h6>Schedule</h6>
                    <p>${formatSchedule(action)}</p>
                </div>
                <div class="col-md-6">
                    <h6>Context Mode</h6>
                    <p><span class="badge ${action.context_mode === 'cumulative' ? 'bg-info' : 'bg-secondary'}">${action.context_mode}</span></p>

                    <h6>Status</h6>
                    <p>${action.is_enabled ? '<span class="badge bg-success">Enabled</span>' : '<span class="badge bg-danger">Disabled</span>'}</p>

                    <h6>Failures</h6>
                    <p>${action.failure_count} / ${action.max_failures}</p>

                    <h6>Last Run</h6>
                    <p>${action.last_run_at ? formatTimestamp(action.last_run_at) : 'Never'}</p>

                    <h6>Next Run</h6>
                    <p>${action.next_run_at ? formatTimestamp(action.next_run_at) : 'Not scheduled'}</p>
                </div>
            </div>

            <h6>Action Prompt</h6>
            <pre class="bg-dark p-3 rounded">${escapeHtml(action.action_prompt)}</pre>

            ${action.tool_permissions && action.tool_permissions.length > 0 ? `
                <h6>Tool Permissions</h6>
                <ul class="list-unstyled">
                    ${action.tool_permissions.map(tp => `
                        <li>
                            <i class="bi ${tp.permission_state === 'allowed' ? 'bi-check-circle text-success' : 'bi-x-circle text-danger'}"></i>
                            ${escapeHtml(tp.tool_name)}
                            ${tp.server_name ? `<small class="text-muted">(${escapeHtml(tp.server_name)})</small>` : ''}
                        </li>
                    `).join('')}
                </ul>
            ` : ''}
        `;

        const modal = new bootstrap.Modal(document.getElementById('viewActionModal'));
        modal.show();

    } catch (error) {
        console.error('Error viewing action:', error);
        showToast('Failed to load action details', 'error');
    }
}

/**
 * Enable an action
 */
async function enableAction(actionId) {
    try {
        const response = await fetch(`/api/actions/${actionId}/enable`, { method: 'POST' });
        if (!response.ok) throw new Error('Failed to enable action');

        showToast('Action enabled', 'success');
        loadActions();
        checkFailedActions();

    } catch (error) {
        console.error('Error enabling action:', error);
        showToast('Failed to enable action', 'error');
    }
}

/**
 * Disable an action
 */
async function disableAction(actionId) {
    try {
        const response = await fetch(`/api/actions/${actionId}/disable`, { method: 'POST' });
        if (!response.ok) throw new Error('Failed to disable action');

        showToast('Action disabled', 'success');
        loadActions();

    } catch (error) {
        console.error('Error disabling action:', error);
        showToast('Failed to disable action', 'error');
    }
}

/**
 * Run action now (manual trigger)
 */
async function runActionNow(actionId) {
    try {
        showToast('Running action...', 'info');

        const response = await fetch(`/api/actions/${actionId}/run-now`, { method: 'POST' });
        if (!response.ok) throw new Error('Failed to trigger action');

        showToast('Action triggered successfully', 'success');

        // Reload after a short delay to show the new run
        setTimeout(() => {
            loadActions();
            loadRecentRuns();
        }, 2000);

    } catch (error) {
        console.error('Error running action:', error);
        showToast('Failed to trigger action', 'error');
    }
}

/**
 * Show delete confirmation
 */
function confirmDeleteAction(actionId, actionName) {
    currentActionId = actionId;
    document.getElementById('deleteActionName').textContent = actionName;

    document.getElementById('confirmDeleteBtn').onclick = () => deleteAction(actionId);

    const modal = new bootstrap.Modal(document.getElementById('confirmDeleteModal'));
    modal.show();
}

/**
 * Delete an action
 */
async function deleteAction(actionId) {
    try {
        const response = await fetch(`/api/actions/${actionId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete action');

        showToast('Action deleted', 'success');

        bootstrap.Modal.getInstance(document.getElementById('confirmDeleteModal')).hide();
        loadActions();
        loadRecentRuns();
        checkFailedActions();

    } catch (error) {
        console.error('Error deleting action:', error);
        showToast('Failed to delete action', 'error');
    }
}

// =============================================================================
// RUNS MANAGEMENT
// =============================================================================

/**
 * View runs for a specific action
 */
async function viewActionRuns(actionId, actionName) {
    currentActionId = actionId;
    document.getElementById('actionRunsTitle').textContent = `Runs: ${actionName}`;

    const tbody = document.getElementById('actionRunsTbody');
    tbody.innerHTML = '<tr><td colspan="6" class="text-center"><div class="spinner-border spinner-border-sm"></div> Loading...</td></tr>';

    const modal = new bootstrap.Modal(document.getElementById('actionRunsModal'));
    modal.show();

    try {
        const response = await fetch(`/api/actions/${actionId}/runs?limit=50`);
        if (!response.ok) throw new Error('Failed to load runs');

        const runs = await response.json();

        if (runs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No runs yet</td></tr>';
            return;
        }

        tbody.innerHTML = runs.map(run => `
            <tr>
                <td>${run.id}</td>
                <td>${formatTimestamp(run.started_at)}</td>
                <td>${run.completed_at ? formatTimestamp(run.completed_at) : '-'}</td>
                <td>${formatRunStatus(run.status)}</td>
                <td>${formatTokens(run.input_tokens, run.output_tokens)}</td>
                <td>
                    <button class="btn btn-sm btn-outline-secondary" onclick="viewRunDetails(${actionId}, ${run.id})">
                        <i class="bi bi-eye"></i> View
                    </button>
                </td>
            </tr>
        `).join('');

    } catch (error) {
        console.error('Error loading runs:', error);
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-danger">Failed to load runs</td></tr>';
    }
}

/**
 * View details of a specific run
 */
async function viewRunDetails(actionId, runId) {
    currentActionId = actionId;
    currentRunId = runId;

    const body = document.getElementById('runDetailsBody');
    body.innerHTML = '<div class="text-center"><div class="spinner-border"></div> Loading...</div>';

    const modal = new bootstrap.Modal(document.getElementById('runDetailsModal'));
    modal.show();

    try {
        const response = await fetch(`/api/actions/${actionId}/runs/${runId}`);
        if (!response.ok) throw new Error('Failed to load run details');

        const run = await response.json();

        body.innerHTML = `
            <div class="row mb-3">
                <div class="col-md-3">
                    <h6>Status</h6>
                    <p>${formatRunStatus(run.status)}</p>
                </div>
                <div class="col-md-3">
                    <h6>Started</h6>
                    <p>${formatTimestamp(run.started_at)}</p>
                </div>
                <div class="col-md-3">
                    <h6>Completed</h6>
                    <p>${run.completed_at ? formatTimestamp(run.completed_at) : '-'}</p>
                </div>
                <div class="col-md-3">
                    <h6>Tokens</h6>
                    <p>${formatTokens(run.input_tokens, run.output_tokens)}</p>
                </div>
            </div>

            ${run.error_message ? `
                <div class="alert alert-danger">
                    <h6><i class="bi bi-exclamation-triangle"></i> Error</h6>
                    <pre class="mb-0">${escapeHtml(run.error_message)}</pre>
                </div>
            ` : ''}

            <h6>Result</h6>
            <div class="card">
                <div class="card-body markdown-content" style="max-height: 400px; overflow-y: auto;">
                    ${run.result_html || (run.result_text ? `<pre>${escapeHtml(run.result_text)}</pre>` : '<p class="text-muted">No result</p>')}
                </div>
            </div>
        `;

    } catch (error) {
        console.error('Error loading run details:', error);
        body.innerHTML = '<div class="alert alert-danger">Failed to load run details</div>';
    }
}

/**
 * Export run result
 */
async function exportRun(format) {
    if (!currentActionId || !currentRunId) return;

    try {
        const response = await fetch(`/api/actions/${currentActionId}/runs/${currentRunId}/export?format=${format}`);
        if (!response.ok) throw new Error('Failed to export run');

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `run_${currentRunId}.${format === 'markdown' ? 'md' : format}`;
        link.click();
        URL.revokeObjectURL(url);

        showToast('Export downloaded', 'success');

    } catch (error) {
        console.error('Error exporting run:', error);
        showToast('Failed to export run', 'error');
    }
}

// =============================================================================
// HELPERS AND FORMATTING
// =============================================================================

/**
 * Load available models for dropdown
 */
async function loadModels() {
    try {
        const response = await fetch('/api/models');
        if (!response.ok) throw new Error('Failed to load models');

        const data = await response.json();
        availableModels = data.models || data;

        const select = document.getElementById('actionModel');
        select.innerHTML = '<option value="">Select a model...</option>';

        availableModels.forEach(model => {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = `${model.name} (${model.provider})`;
            select.appendChild(option);
        });

    } catch (error) {
        console.error('Error loading models:', error);
    }
}

/**
 * Load available tools for permissions
 */
async function loadTools() {
    try {
        const response = await fetch('/api/tools');
        if (!response.ok) throw new Error('Failed to load tools');

        const data = await response.json();
        availableTools = data.tools || [];

        resetToolPermissions();

    } catch (error) {
        console.error('Error loading tools:', error);
        document.getElementById('toolPermissions').innerHTML = '<p class="text-muted">Failed to load tools</p>';
    }
}

/**
 * Reset tool permissions checkboxes
 */
function resetToolPermissions() {
    const container = document.getElementById('toolPermissions');

    if (availableTools.length === 0) {
        container.innerHTML = '<p class="text-muted mb-0">No tools available</p>';
        return;
    }

    container.innerHTML = availableTools.map(tool => `
        <div class="form-check">
            <input class="form-check-input tool-permission" type="checkbox"
                   id="tool-${tool.name}" data-tool="${tool.name}" data-server="${tool.server || ''}">
            <label class="form-check-label" for="tool-${tool.name}">
                ${escapeHtml(tool.name)}
                ${tool.server ? `<small class="text-muted">(${escapeHtml(tool.server)})</small>` : ''}
            </label>
        </div>
    `).join('');
}

/**
 * Set tool permissions from action data
 */
function setToolPermissions(permissions) {
    // First reset all
    document.querySelectorAll('.tool-permission').forEach(cb => cb.checked = false);

    // Then set the allowed ones
    permissions.forEach(perm => {
        if (perm.permission_state === 'allowed') {
            const cb = document.querySelector(`.tool-permission[data-tool="${perm.tool_name}"]`);
            if (cb) cb.checked = true;
        }
    });
}

/**
 * Get tool permissions from checkboxes
 */
function getToolPermissions() {
    const permissions = [];

    document.querySelectorAll('.tool-permission:checked').forEach(cb => {
        permissions.push({
            tool_name: cb.dataset.tool,
            server_name: cb.dataset.server || null,
            permission_state: 'allowed'
        });
    });

    return permissions;
}

/**
 * Update schedule config visibility
 */
function updateScheduleConfig() {
    const scheduleType = document.getElementById('scheduleType').value;
    document.getElementById('oneOffConfig').classList.toggle('d-none', scheduleType !== 'one_off');
    document.getElementById('recurringConfig').classList.toggle('d-none', scheduleType !== 'recurring');
}

/**
 * Format schedule for display
 */
function formatSchedule(action) {
    if (action.schedule_type === 'one_off') {
        const date = action.schedule_config?.run_date;
        return date ? `<i class="bi bi-calendar-event"></i> ${formatTimestamp(date)}` : 'One-off';
    } else {
        const cron = action.schedule_config?.cron_expression;
        return cron ? `<i class="bi bi-arrow-repeat"></i> <code>${escapeHtml(cron)}</code>` : 'Recurring';
    }
}

/**
 * Format failures with colour coding
 */
function formatFailures(action) {
    const ratio = action.failure_count / action.max_failures;
    let badgeClass = 'bg-secondary';
    if (ratio >= 1) badgeClass = 'bg-danger';
    else if (ratio >= 0.5) badgeClass = 'bg-warning text-dark';

    return `<span class="badge ${badgeClass}">${action.failure_count}/${action.max_failures}</span>`;
}

/**
 * Format run status badge
 */
function formatRunStatus(status) {
    const badges = {
        'completed': '<span class="badge bg-success">Completed</span>',
        'running': '<span class="badge bg-primary">Running</span>',
        'failed': '<span class="badge bg-danger">Failed</span>'
    };
    return badges[status] || `<span class="badge bg-secondary">${status}</span>`;
}

/**
 * Format duration between two timestamps
 */
function formatDuration(start, end) {
    if (!start || !end) return '-';

    const startDate = new Date(start);
    const endDate = new Date(end);
    const diffMs = endDate - startDate;

    if (diffMs < 1000) return '<1s';
    if (diffMs < 60000) return `${Math.round(diffMs / 1000)}s`;
    if (diffMs < 3600000) return `${Math.round(diffMs / 60000)}m`;
    return `${Math.round(diffMs / 3600000)}h`;
}

/**
 * Format token counts
 */
function formatTokens(input, output) {
    if (!input && !output) return '-';
    return `${(input || 0).toLocaleString()} / ${(output || 0).toLocaleString()}`;
}

/**
 * Format timestamp for display
 */
function formatTimestamp(timestamp) {
    if (!timestamp) return '-';
    try {
        const date = new Date(timestamp);
        return date.toLocaleString();
    } catch (e) {
        return timestamp;
    }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (typeof text !== 'string') return text;
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}


// =============================================================================
// AI-ASSISTED ACTION CREATION
// =============================================================================

// State for AI creation session
let aiCreationId = null;
let aiCreatedActionId = null;

/**
 * Show the AI creation modal
 */
function showAICreateModal() {
    // Reset form and state
    aiCreationId = null;
    aiCreatedActionId = null;
    document.getElementById('aiActionName').value = '';
    document.getElementById('aiActionDescription').value = '';
    document.getElementById('aiActionModel').value = '';
    document.getElementById('aiChatMessages').innerHTML = '';

    // Populate model dropdown from the main form's dropdown
    const mainModelSelect = document.getElementById('actionModel');
    const aiModelSelect = document.getElementById('aiActionModel');
    aiModelSelect.innerHTML = mainModelSelect.innerHTML;

    // Show setup form, hide chat interface
    document.getElementById('aiCreateSetup').classList.remove('d-none');
    document.getElementById('aiCreateChat').classList.add('d-none');
    document.getElementById('aiCreateLoading').classList.add('d-none');

    // Show footer with cancel button
    document.getElementById('aiCreateFooter').classList.remove('d-none');

    const modal = new bootstrap.Modal(document.getElementById('aiCreateModal'));
    modal.show();
}

/**
 * Start the AI-assisted creation session
 */
async function startAICreation() {
    const name = document.getElementById('aiActionName').value.trim();
    const description = document.getElementById('aiActionDescription').value.trim();
    const modelId = document.getElementById('aiActionModel').value;

    // Validate inputs
    if (!name) {
        showToast('Please enter an action name', 'error');
        return;
    }
    if (!description) {
        showToast('Please enter a description', 'error');
        return;
    }
    if (!modelId) {
        showToast('Please select a model', 'error');
        return;
    }

    // Show loading
    document.getElementById('aiCreateSetup').classList.add('d-none');
    document.getElementById('aiCreateLoading').classList.remove('d-none');

    try {
        const response = await fetch('/api/actions/ai-create/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                description: description,
                model_id: modelId
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to start AI creation');
        }

        const data = await response.json();
        aiCreationId = data.creation_id;

        // Update chat header
        document.getElementById('aiChatActionName').textContent = name;
        document.getElementById('aiChatModelName').textContent = modelId;

        // Show chat interface
        document.getElementById('aiCreateLoading').classList.add('d-none');
        document.getElementById('aiCreateChat').classList.remove('d-none');

        // Add initial AI response to chat
        addAIChatMessage(data.response, 'assistant');

        // Focus on input
        document.getElementById('aiChatInput').focus();

        // Check if action was created immediately
        if (data.completed) {
            handleAICreationComplete(data.action_id);
        }

    } catch (error) {
        console.error('Error starting AI creation:', error);
        showToast(error.message, 'error');

        // Show setup form again
        document.getElementById('aiCreateLoading').classList.add('d-none');
        document.getElementById('aiCreateSetup').classList.remove('d-none');
    }
}

/**
 * Send a message in the AI creation chat
 */
async function sendAICreationMessage() {
    const input = document.getElementById('aiChatInput');
    const message = input.value.trim();

    if (!message) return;
    if (!aiCreationId) {
        showToast('No active creation session', 'error');
        return;
    }

    // Add user message to chat
    addAIChatMessage(message, 'user');
    input.value = '';

    // Disable input while waiting
    input.disabled = true;
    document.querySelector('#aiChatInputArea button').disabled = true;

    // Show typing indicator
    const typingDiv = document.createElement('div');
    typingDiv.id = 'aiTypingIndicator';
    typingDiv.className = 'mb-2 text-muted small';
    typingDiv.innerHTML = '<i class="bi bi-three-dots"></i> AI is thinking...';
    document.getElementById('aiChatMessages').appendChild(typingDiv);
    scrollChatToBottom();

    try {
        const response = await fetch(`/api/actions/ai-create/${aiCreationId}/message`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message })
        });

        // Remove typing indicator
        const indicator = document.getElementById('aiTypingIndicator');
        if (indicator) indicator.remove();

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to send message');
        }

        const data = await response.json();

        // Add AI response to chat
        if (data.response) {
            addAIChatMessage(data.response, 'assistant');
        }

        // Check if action was created
        if (data.completed) {
            handleAICreationComplete(data.action_id);
        } else {
            // Re-enable input
            input.disabled = false;
            document.querySelector('#aiChatInputArea button').disabled = false;
            input.focus();
        }

    } catch (error) {
        console.error('Error sending message:', error);
        showToast(error.message, 'error');

        // Remove typing indicator
        const indicator = document.getElementById('aiTypingIndicator');
        if (indicator) indicator.remove();

        // Re-enable input
        input.disabled = false;
        document.querySelector('#aiChatInputArea button').disabled = false;
    }
}

/**
 * Handle completion of AI creation
 */
function handleAICreationComplete(actionId) {
    aiCreatedActionId = actionId;

    // Update status badge
    document.getElementById('aiChatStatus').textContent = 'Complete';
    document.getElementById('aiChatStatus').classList.remove('bg-primary');
    document.getElementById('aiChatStatus').classList.add('bg-success');

    // Hide input, show completion message
    document.getElementById('aiChatInputArea').classList.add('d-none');
    document.getElementById('aiChatComplete').classList.remove('d-none');

    // Update footer
    document.getElementById('aiCreateFooter').innerHTML = `
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
        <button type="button" class="btn btn-primary" onclick="viewCreatedAction()">
            <i class="bi bi-eye"></i> View Action
        </button>
    `;

    // Refresh actions list
    loadActions();
}

/**
 * Cancel the AI creation session
 */
async function cancelAICreation() {
    if (aiCreationId) {
        try {
            await fetch(`/api/actions/ai-create/${aiCreationId}`, { method: 'DELETE' });
        } catch (error) {
            console.error('Error cancelling creation:', error);
        }
    }

    aiCreationId = null;
    aiCreatedActionId = null;

    // Close modal
    const modal = bootstrap.Modal.getInstance(document.getElementById('aiCreateModal'));
    if (modal) modal.hide();
}

/**
 * View the action that was just created
 */
function viewCreatedAction() {
    if (aiCreatedActionId) {
        // Close AI modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('aiCreateModal'));
        if (modal) modal.hide();

        // View the action
        viewAction(aiCreatedActionId);
    }
}

/**
 * Add a message to the AI chat
 */
function addAIChatMessage(text, role) {
    const container = document.getElementById('aiChatMessages');

    const messageDiv = document.createElement('div');
    messageDiv.className = `mb-2 p-2 rounded ${role === 'user' ? 'bg-primary text-white ms-5' : 'bg-white border me-5'}`;

    // Simple markdown rendering for AI responses
    if (role === 'assistant') {
        // Convert markdown bold and line breaks
        let html = escapeHtml(text);
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\n/g, '<br>');
        messageDiv.innerHTML = html;
    } else {
        messageDiv.textContent = text;
    }

    container.appendChild(messageDiv);
    scrollChatToBottom();
}

/**
 * Scroll the chat container to the bottom
 */
function scrollChatToBottom() {
    const container = document.getElementById('aiChatMessages');
    container.scrollTop = container.scrollHeight;
}

/**
 * Handle Enter key press in AI chat input
 */
function handleAIChatKeypress(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendAICreationMessage();
    }
}
