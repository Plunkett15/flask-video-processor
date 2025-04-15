// --- Start of File: static/js/app.js ---

document.addEventListener('DOMContentLoaded', function() {

    console.log("app.js loaded (Granular Workflow Version).");

    // Helper function for AJAX POST requests (Generic)
    function postRequestGeneric(url, formData, buttonElement, statusElement, successMessage, confirmMessage) {
        return new Promise((resolve, reject) => {
            if (confirmMessage && !confirm(confirmMessage)) {
                if (buttonElement) buttonElement.disabled = false; // Re-enable if cancelled
                reject(new Error("User cancelled."));
                return;
            }

            const originalButtonHTML = buttonElement ? buttonElement.innerHTML : null;
            if (buttonElement) {
                buttonElement.disabled = true;
                buttonElement.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Working...';
            }
            if (statusElement) {
                statusElement.textContent = ' Sending request...';
                statusElement.className = 'ms-2 badge bg-info-subtle text-info-emphasis'; // Use subtle badges
            }

            fetch(url, {
                method: 'POST',
                body: formData, // Can be FormData, URLSearchParams, JSON string, or null
                headers: {
                    // If sending JSON, uncomment and set header:
                    // 'Content-Type': 'application/json',
                    // Add CSRF token header if needed (using Flask-WTF, etc.)
                    // 'X-CSRFToken': '...'
                }
            })
            .then(response => {
                 return response.json().then(data => {
                    if (!response.ok) { throw new Error(data.error || `HTTP error ${response.status}`); }
                    return data;
                }).catch(jsonParseError => {
                     if (!response.ok) { throw new Error(`HTTP error ${response.status}: ${response.statusText}`); }
                     console.error("JSON parse error on OK response:", jsonParseError);
                     throw new Error("Failed to parse server response.");
                 });
            })
            .then(data => {
                if (statusElement) {
                    statusElement.textContent = ` ${successMessage || 'Queued!'}`;
                    statusElement.className = 'ms-2 badge bg-success-subtle text-success-emphasis';
                }
                if (buttonElement) {
                    // Leave button disabled after queuing, rely on SSE for final state? Or brief "Done"?
                    buttonElement.innerHTML = originalButtonHTML; // Revert for now, maybe update based on SSE later
                    // Consider re-disabling based on new status from SSE
                }
                resolve(data);
            })
            .catch(error => {
                console.error('AJAX Post Error:', error);
                if (statusElement) {
                    statusElement.textContent = ` Error: ${error.message || 'Request failed.'}`;
                    statusElement.className = 'ms-2 badge bg-danger-subtle text-danger-emphasis';
                }
                if (buttonElement) {
                    buttonElement.innerHTML = originalButtonHTML || '<i class="bi bi-exclamation-triangle"></i> Error';
                    buttonElement.disabled = false; // Re-enable on failure
                }
                reject(error);
            });
        });
    }

    // --- Get Video ID from a common parent element (assuming one exists) ---
    const videoDetailsContainer = document.getElementById('videoDetailsContainer'); // Add this ID to a top-level div on video_details.html
    const VIDEO_ID = videoDetailsContainer ? videoDetailsContainer.getAttribute('data-video-id') : null;

    // --- Granular Pipeline Step Triggers (Phase 1 - Video Level) ---
    const pipelineControlPanel = document.getElementById('pipelineControlPanel'); // Add this ID to the panel container
    if (pipelineControlPanel && VIDEO_ID) {
        pipelineControlPanel.addEventListener('click', function(event) {
            const button = event.target.closest('button[data-action]');
            if (!button) return; // Exit if click wasn't on a button with data-action

            const action = button.getAttribute('data-action');
            const statusDisplay = document.getElementById(`${action}StatusDisplay`); // Assumes elements like downloadStatusDisplay exist
            let url = `/video/${VIDEO_ID}/trigger_${action}`;
            let confirmMsg = `Are you sure you want to run/re-run the '${action}' step?`;

            // Special handling for 'reset_full'? (If you add such a button)
            // if (action === 'reset_full') { url = ...; }

            console.log(`Triggering action: ${action} for video ${VIDEO_ID}`);

            postRequestGeneric(url, null, button, statusDisplay, `${action.charAt(0).toUpperCase() + action.slice(1)} step queued.`, confirmMsg)
                .catch(err => console.error(`Failed to trigger ${action}:`, err));
        });
    } else if (VIDEO_ID) {
        console.warn("Pipeline control panel element not found.");
    }

    // --- Granular Exchange Substep Triggers (Phase 2 - Exchange Level) ---
    const exchangeTableBody = document.getElementById('exchangeTableBody'); // Add this ID to the tbody of the exchanges table
    if (exchangeTableBody) {
        exchangeTableBody.addEventListener('click', function(event) {
            const button = event.target.closest('button[data-action]');
            if (!button) return;

            const action = button.getAttribute('data-action'); // e.g., 'process_diarization', 'define_clips', 'cut_clips'
            const exchangeId = button.getAttribute('data-exchange-id');
            const statusDisplay = button.closest('td').querySelector('.substep-status-display'); // Find status display in the same cell or row

            if (!exchangeId) { console.error("Missing data-exchange-id attribute."); return; }

            const url = `/exchange/${exchangeId}/trigger_${action}`;
            const confirmMsg = `Are you sure you want to run/re-run '${action.replace('_', ' ')}' for exchange ID ${exchangeId}?`;

            console.log(`Triggering exchange action: ${action} for exchange ${exchangeId}`);

            postRequestGeneric(url, null, button, statusDisplay, `${action.replace('_', ' ')} queued.`, confirmMsg)
                 .catch(err => console.error(`Failed to trigger ${action} for exchange ${exchangeId}:`, err));
        });
    }

    // --- Manual Exchange Marking ---
    const markManualExchangeForm = document.getElementById('markManualExchangeForm'); // Add this ID to a form/div containing manual inputs
    if (markManualExchangeForm && VIDEO_ID) {
        markManualExchangeForm.addEventListener('submit', function(event) {
             event.preventDefault();
             const button = markManualExchangeForm.querySelector('button[type="submit"]');
             const statusDisplay = document.getElementById('manualMarkStatusDisplay'); // Add a status element

             const startTimeInput = document.getElementById('manualStartTime');
             const endTimeInput = document.getElementById('manualEndTime');
             // const labelInput = document.getElementById('manualExchangeLabel'); // Optional

             const startTime = parseFloat(startTimeInput.value);
             const endTime = parseFloat(endTimeInput.value);
             // const label = labelInput ? labelInput.value : 'Manual Exchange';

             if (isNaN(startTime) || isNaN(endTime) || startTime < 0 || endTime <= startTime) {
                  if (statusDisplay) {
                       statusDisplay.textContent = " Invalid start/end time.";
                       statusDisplay.className = 'ms-2 badge bg-warning-subtle text-warning-emphasis';
                  }
                  return;
             }

             const formData = new URLSearchParams(); // Use URLSearchParams for simple key-value pairs
             formData.append('start_time', startTime);
             formData.append('end_time', endTime);
             // formData.append('label', label);

             const url = `/video/${VIDEO_ID}/mark_manual_exchange`;

             postRequestGeneric(url, formData, button, statusDisplay, "Manual exchange saved.", null)
                 .then(data => {
                      console.log("Manual exchange marked:", data);
                      // OPTIONAL: Refresh exchange list or dynamically add the new row
                      // Simple approach: reload after a short delay
                      if (statusDisplay) statusDisplay.textContent += " Reloading list...";
                      setTimeout(() => window.location.reload(), 1500);
                 })
                 .catch(err => console.error("Failed to mark manual exchange:", err));
        });
    }

    // --- Server-Sent Events (SSE) for Status Updates ---
    const videoTableBodyIndex = document.querySelector('#deleteVideosForm table tbody'); // For index page
    const ssePath = '/stream_updates'; // Same endpoint

    if (videoTableBodyIndex || videoDetailsContainer) { // Connect if on index OR details page
        console.log("Attempting SSE connection...");
        const eventSource = new EventSource(ssePath);

        eventSource.onopen = function() {
            console.log("SSE connection established.");
        };

        eventSource.onerror = function(err) {
            console.error("SSE connection error:", err);
            // Optional: Implement retry logic or display connection error message
             // Simple message display
             const sseStatusEl = document.getElementById('sseStatus'); // Add this element to base.html or specific pages
             if (sseStatusEl) {
                  sseStatusEl.innerHTML = '<i class="bi bi-exclamation-triangle-fill text-danger"></i> Status updates disconnected. Refresh needed.';
                  sseStatusEl.className = 'text-danger small';
             }
        };

        eventSource.onmessage = function(event) {
            try {
                const data = JSON.parse(event.data);
                // console.log("SSE data received:", data); // DEBUG

                // --- Update Logic for BOTH Index and Details Page ---
                for (const videoId in data) {
                    if (data.hasOwnProperty(videoId)) {
                        const videoUpdates = data[videoId];

                        // --- Index Page Updates (if elements exist) ---
                        const row = videoTableBodyIndex ? videoTableBodyIndex.querySelector(`tr[data-video-id="${videoId}"]`) : null;
                        if (row) {
                            // Derive overall status for index page (more complex now)
                            let overallStatus = 'Unknown';
                            let currentStep = 'Idle';
                            let hasError = false;

                            // Logic to determine simplified status (adapt as needed)
                            if (Object.values(videoUpdates).includes('Error')) {
                                overallStatus = 'Error'; hasError = true;
                                currentStep = 'Error'; // Find specific error step if needed
                            } else if (Object.values(videoUpdates).includes('Running')) {
                                overallStatus = 'Processing';
                                // Find the first running step
                                const runningStep = Object.keys(videoUpdates).find(key => videoUpdates[key] === 'Running');
                                currentStep = runningStep ? runningStep.replace('_status', '').replace('_', ' ') : 'Running...';
                            } else if (Object.values(videoUpdates).includes('Queued')) {
                                overallStatus = 'Queued';
                                currentStep = 'Queued';
                            } else if (Object.values(videoUpdates).every(status => status === 'Complete' || status === 'Pending' || status === 'Skipped')) {
                                 // Check if *all* necessary steps are complete for final state
                                 // Simplified: If no errors/running/queued, assume 'Processed' or 'Pending'
                                 if (videoUpdates['download_status'] === 'Complete') { // Simple check
                                      overallStatus = 'Processed'; // Could mean Phase 1 done, or further
                                      currentStep = 'Ready for Next Step';
                                 } else {
                                      overallStatus = 'Pending';
                                      currentStep = 'Pending Download';
                                 }
                            }

                            // Update Index Table Cells
                            const statusCell = row.querySelector(`#status-cell-${videoId}`);
                            const stepCell = row.querySelector(`#step-cell-${videoId}`);
                            const updatedCell = row.querySelector(`#updated-cell-${videoId}`);

                            if (statusCell) {
                                statusCell.innerHTML = `<span class="badge rounded-pill status-${overallStatus.toLowerCase()}">${overallStatus}</span>`;
                            }
                            if (stepCell) {
                                stepCell.innerHTML = `<span class="processing-status">${currentStep}</span>`;
                                row.className = hasError ? 'table-danger' : (overallStatus === 'Processed' ? 'table-success' : '');
                            }
                            if (updatedCell) {
                                updatedCell.textContent = videoUpdates.updated_at || 'N/A';
                            }
                        }

                        // --- Details Page Updates (if elements exist) ---
                        if (videoDetailsContainer && VIDEO_ID === videoId) {
                             // Update granular status badges and buttons
                            for (const statusKey in videoUpdates) {
                                 if (videoUpdates.hasOwnProperty(statusKey) && statusKey.endsWith('_status')) {
                                     const stepName = statusKey.replace('_status', '');
                                     const statusValue = videoUpdates[statusKey];
                                     const badge = document.getElementById(`${stepName}StatusBadge`);
                                     const button = document.querySelector(`button[data-action='${stepName}']`);

                                     if (badge) {
                                         badge.textContent = statusValue;
                                         badge.className = `badge rounded-pill status-${statusValue.toLowerCase()} p-1`; // Update class for color
                                     }
                                     // Optionally update button state based on new status
                                     // e.g., if (button && statusValue === 'Complete') button.disabled = true;
                                     //       else if (button) button.disabled = false;
                                     // This needs careful coordination with prerequisite logic
                                 }
                            }
                            // Update exchange substep statuses would require more complex logic
                            // Fetching exchange data via another AJAX call or enhancing SSE payload
                        }
                    }
                }
            } catch (e) {
                console.error("Error processing SSE message:", e, "Data:", event.data);
            }
        }; // end onmessage

    } else {
        console.log("Not on index or details page, or required elements missing. SSE connection not started.");
    }

    // --- Index Page: Delete selection Logic ---
    // (Keep existing logic for index page checkboxes and delete button)
    const selectAllCheckbox = document.getElementById('selectAll');
    const videoCheckboxes = document.querySelectorAll('.video-checkbox');
    const deleteButton = document.getElementById('deleteSelectedButton');
    function toggleDeleteButtonState() {
         if (!deleteButton) return;
         const anyChecked = Array.from(videoCheckboxes).some(cb => cb.checked);
         deleteButton.disabled = !anyChecked;
     }
    if (selectAllCheckbox) {
         selectAllCheckbox.addEventListener('change', function() {
              videoCheckboxes.forEach(checkbox => { checkbox.checked = this.checked; });
              toggleDeleteButtonState();
         });
     }
    videoCheckboxes.forEach(checkbox => {
         checkbox.addEventListener('change', toggleDeleteButtonState);
     });
    toggleDeleteButtonState(); // Initial check

    // --- Initialize button states on details page based on initial statuses ---
    // TODO: Add logic here or use server-side Jinja to set initial disabled states
    // for granular trigger buttons based on prerequisite statuses loaded from the DB.

}); // End DOMContentLoaded

// Function to map status to Bootstrap badge class (example)
function getStatusClass(status) {
    status = status ? status.toLowerCase() : 'unknown';
    switch (status) {
        case 'complete': return 'bg-success-subtle text-success-emphasis';
        case 'running': return 'bg-info-subtle text-info-emphasis';
        case 'queued': return 'bg-secondary-subtle text-secondary-emphasis';
        case 'pending': return 'bg-light-subtle text-emphasis-light'; // Or another subtle color
        case 'error': return 'bg-danger-subtle text-danger-emphasis';
        case 'skipped': return 'bg-warning-subtle text-warning-emphasis';
        default: return 'bg-secondary-subtle text-secondary-emphasis';
    }
}


// --- END OF FILE: static/js/app.js ---