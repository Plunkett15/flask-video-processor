// --- Start of File: static/js/app.js ---

document.addEventListener('DOMContentLoaded', function() {

    console.log("app.js loaded (Refactored Tasks Version).");

    // Helper function for AJAX POST requests (Generic)
    // (postRequestGeneric function remains the same as before)
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
                body: formData,
                headers: {
                    // Add CSRF token header if needed
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
                    // Revert button text, but leave it disabled. SSE updates will manage re-enabling.
                    buttonElement.innerHTML = originalButtonHTML;
                    // buttonElement.disabled = false; // <<< REMOVED: Don't re-enable here
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

    // --- Get Video ID from a common parent element ---
    const videoDetailsContainer = document.getElementById('videoDetailsContainer');
    const VIDEO_ID = videoDetailsContainer ? videoDetailsContainer.getAttribute('data-video-id') : null;

    // --- Granular Pipeline Step Triggers (Phase 1 - Video Level) ---
    const pipelineControlPanel = document.getElementById('pipelineControlPanel');
    if (pipelineControlPanel && VIDEO_ID) {
        pipelineControlPanel.addEventListener('click', function(event) {
            const button = event.target.closest('button[data-action]');
            if (!button) return;

            const action = button.getAttribute('data-action');
            const statusDisplay = document.getElementById(`${action}StatusDisplay`);
            // <<< MODIFIED: Updated route names to match app.py >>>
            let routeName = action;
            if (action === 'diarization') routeName = 'diarization'; // Route uses 'diarization' now
            if (action === 'exchange_id') routeName = 'exchange_id'; // Route uses 'exchange_id' now
            let url = `/video/${VIDEO_ID}/trigger_${routeName}`;
            let confirmMsg = `Are you sure you want to run/re-run the '${action.replace('_', ' ').replace(' id', ' ID')}' step?`;

            console.log(`Triggering action: ${action} for video ${VIDEO_ID} via URL ${url}`);

            postRequestGeneric(url, null, button, statusDisplay, `${action.replace('_', ' ').replace(' id', ' ID').capitalize()} step queued.`, confirmMsg)
                .catch(err => console.error(`Failed to trigger ${action}:`, err));
        });
    } else if (VIDEO_ID) {
        console.warn("Pipeline control panel element not found.");
    }

    // --- Granular Exchange Substep Triggers (Phase 2 - Exchange Level) ---
    const exchangeTableBody = document.getElementById('exchangeTableBody');
    if (exchangeTableBody && VIDEO_ID) { // Need VIDEO_ID here too? Yes, for context.
        exchangeTableBody.addEventListener('click', function(event) {
            const button = event.target.closest('button[data-action]');
            if (!button) return;

            const action = button.getAttribute('data-action'); // e.g., 'process_diarization', 'define_clips', 'cut_clips'
            const exchangeId = button.getAttribute('data-exchange-id');
            const statusDisplay = button.closest('td').querySelector('.substep-status-display');

            if (!exchangeId) { console.error("Missing data-exchange-id attribute."); return; }

            // <<< MODIFIED: Updated route name >>>
            const url = `/exchange/${exchangeId}/trigger_${action}`;
            const confirmMsg = `Are you sure you want to run/re-run '${action.replace('_', ' ')}' for exchange ID ${exchangeId}?`;

            console.log(`Triggering exchange action: ${action} for exchange ${exchangeId}`);

            postRequestGeneric(url, null, button, statusDisplay, `${action.replace('_', ' ')} queued.`, confirmMsg)
                 .catch(err => console.error(`Failed to trigger ${action} for exchange ${exchangeId}:`, err));
        });
    }

    // --- Manual Exchange Marking ---
    // (Manual Marking logic remains the same)
    const markManualExchangeForm = document.getElementById('markManualExchangeForm');
    if (markManualExchangeForm && VIDEO_ID) {
        markManualExchangeForm.addEventListener('submit', function(event) {
             event.preventDefault();
             const button = markManualExchangeForm.querySelector('button[type="submit"]');
             const statusDisplay = document.getElementById('manualMarkStatusDisplay');

             const startTimeInput = document.getElementById('manualStartTime');
             const endTimeInput = document.getElementById('manualEndTime');

             const startTime = parseFloat(startTimeInput.value);
             const endTime = parseFloat(endTimeInput.value);

             if (isNaN(startTime) || isNaN(endTime) || startTime < 0 || endTime <= startTime) {
                  if (statusDisplay) {
                       statusDisplay.textContent = " Invalid start/end time.";
                       statusDisplay.className = 'ms-2 badge bg-warning-subtle text-warning-emphasis';
                  }
                  return;
             }

             const formData = new URLSearchParams();
             formData.append('start_time', startTime);
             formData.append('end_time', endTime);

             const url = `/video/${VIDEO_ID}/mark_manual_exchange`;

             postRequestGeneric(url, formData, button, statusDisplay, "Manual exchange saved.", null)
                 .then(data => {
                      console.log("Manual exchange marked:", data);
                      if (statusDisplay) statusDisplay.textContent += " Reloading list...";
                      setTimeout(() => window.location.reload(), 1500);
                 })
                 .catch(err => console.error("Failed to mark manual exchange:", err));
        });
    }

    // --- Server-Sent Events (SSE) for Status Updates ---
    const videoTableBodyIndex = document.querySelector('#deleteVideosForm table tbody');
    const ssePath = '/stream_updates';

    if (videoTableBodyIndex || videoDetailsContainer) {
        console.log("Attempting SSE connection...");
        const eventSource = new EventSource(ssePath);

        eventSource.onopen = function() {
            console.log("SSE connection established.");
             const sseStatusEl = document.getElementById('sseStatus');
             if (sseStatusEl) { sseStatusEl.innerHTML = ''; } // Clear any previous error
        };

        eventSource.onerror = function(err) {
            console.error("SSE connection error:", err);
             const sseStatusEl = document.getElementById('sseStatus');
             if (sseStatusEl) {
                  sseStatusEl.innerHTML = '<i class="bi bi-exclamation-triangle-fill text-danger"></i> Status updates disconnected. Refresh needed.';
                  sseStatusEl.className = 'text-danger small';
             }
        };

        // <<< MODIFIED: Enhanced SSE message handler >>>
        eventSource.onmessage = function(event) {
            try {
                const data = JSON.parse(event.data);
                // console.log("SSE data received:", data);

                for (const videoId in data) {
                    if (data.hasOwnProperty(videoId)) {
                        const videoUpdates = data[videoId]; // Contains granular statuses + updated_at

                        // --- Index Page Updates (Simplified using helper function conceptually) ---
                        const row = videoTableBodyIndex ? videoTableBodyIndex.querySelector(`tr[data-video-id="${videoId}"]`) : null;
                        if (row) {
                            // Note: Python helper `_calculate_overall_status` runs on server for initial load.
                            // JS needs to replicate this logic or make assumptions based on granular states.
                            // Let's update based on granular states received.

                            let overallStatus = 'Unknown'; let currentStep = 'Idle'; let hasError = false;
                            let overallStatusClass = 'unknown';

                            // Basic derivation logic (can be refined)
                            const statuses = Object.values(videoUpdates).filter(v => typeof v === 'string'); // Get status strings
                            if (statuses.includes('Error')) { overallStatus = 'Error'; hasError = true; overallStatusClass = 'error'; }
                            else if (statuses.includes('Running')) { overallStatus = 'Processing'; overallStatusClass = 'processing'; }
                            else if (statuses.includes('Queued')) { overallStatus = 'Queued'; overallStatusClass = 'queued'; }
                            else if (statuses.every(s => ['Complete', 'Pending', 'Skipped', 'Unknown'].includes(s))) {
                                if (videoUpdates['download_status'] === 'Complete') {
                                     // Check if all essential steps are done
                                     const requiredSteps = ['download_status', 'audio_status', 'transcript_status', 'diarization_status', 'exchange_id_status'];
                                     const allDone = requiredSteps.every(step => videoUpdates[step] === 'Complete');
                                     if (allDone) { overallStatus = 'Complete'; overallStatusClass = 'complete'; currentStep = 'All Steps Complete';}
                                     else { overallStatus = 'Ready'; overallStatusClass = 'ready'; currentStep = 'Ready for Next Step';}
                                } else {
                                     overallStatus = 'Pending'; overallStatusClass = 'pending'; currentStep = 'Pending Download';
                                }
                            }
                            // Find current step text more accurately
                            if (hasError) { /* Find error step */
                                if (videoUpdates.download_status === 'Error') currentStep = 'Download Failed';
                                else if (videoUpdates.audio_status === 'Error') currentStep = 'Audio Ext. Failed';
                                else if (videoUpdates.transcript_status === 'Error') currentStep = 'Transcript Failed';
                                else if (videoUpdates.diarization_status === 'Error') currentStep = 'Diarization Failed';
                                else if (videoUpdates.exchange_id_status === 'Error') currentStep = 'Exchange ID Failed';
                                else currentStep = 'Processing Error';
                            } else if (overallStatus === 'Processing') { /* Find running step */
                                if (videoUpdates.download_status === 'Running') currentStep = 'Downloading...';
                                else if (videoUpdates.audio_status === 'Running') currentStep = 'Extracting Audio...';
                                else if (videoUpdates.transcript_status === 'Running') currentStep = 'Transcribing...';
                                else if (videoUpdates.diarization_status === 'Running') currentStep = 'Diarizing...';
                                else if (videoUpdates.exchange_id_status === 'Running') currentStep = 'Finding Exchanges...';
                                else currentStep = 'Processing...';
                            } else if (overallStatus === 'Queued') { /* Find queued step */
                                 if (videoUpdates.download_status === 'Queued') currentStep = 'Queued for Download';
                                 else if (videoUpdates.audio_status === 'Queued') currentStep = 'Queued for Audio';
                                 else if (videoUpdates.transcript_status === 'Queued') currentStep = 'Queued for Transcript';
                                 else if (videoUpdates.diarization_status === 'Queued') currentStep = 'Queued for Diarization';
                                 else if (videoUpdates.exchange_id_status === 'Queued') currentStep = 'Queued for Exchange ID';
                                 else currentStep = 'Queued';
                            }

                            // Update Index Table Cells
                            const statusCell = row.querySelector(`#status-cell-${videoId}`);
                            const stepCell = row.querySelector(`#step-cell-${videoId}`);
                            const updatedCell = row.querySelector(`#updated-cell-${videoId}`);

                            if (statusCell) {
                                statusCell.innerHTML = `<span class="badge rounded-pill status-${overallStatusClass}">${overallStatus}</span>`;
                            }
                            if (stepCell) {
                                stepCell.innerHTML = `<span class="processing-status">${currentStep}</span>`;
                                // Update row class based on overall status
                                let newClass = '';
                                if (hasError) newClass = 'table-danger';
                                else if (overallStatus === 'Complete') newClass = 'table-success';
                                else if (overallStatus === 'Ready') newClass = 'table-info';
                                row.className = newClass;
                            }
                            if (updatedCell) {
                                updatedCell.textContent = videoUpdates.updated_at || 'N/A'; // Use H:M:S format from SSE
                            }
                        }

                        // --- Details Page Updates ---
                        if (videoDetailsContainer && VIDEO_ID === videoId) {
                             // Update granular status badges
                            for (const statusKey in videoUpdates) {
                                 if (videoUpdates.hasOwnProperty(statusKey) && statusKey.endsWith('_status')) {
                                     const stepName = statusKey.replace('_status', '');
                                     const statusValue = videoUpdates[statusKey];
                                     const badge = document.getElementById(`${stepName}StatusBadge`);

                                     if (badge) {
                                         badge.textContent = statusValue;
                                         // Use utility function for class mapping
                                         badge.className = `badge rounded-pill ${getStatusClass(statusValue)} status-badge`; // Updated class name
                                     }
                                 }
                            }

                            // --- Update Video-Level Button States ---
                            updateVideoButtonState('download', videoUpdates);
                            updateVideoButtonState('audio', videoUpdates);
                            updateVideoButtonState('transcript', videoUpdates);
                            updateVideoButtonState('diarization', videoUpdates); // Matches trigger_diarization route action
                            updateVideoButtonState('exchange_id', videoUpdates); // Matches trigger_exchange_id route action

                            // TODO: Update exchange-level buttons? Requires more complex SSE/JS logic.
                            // updateExchangeButtonStates(videoUpdates); // Placeholder if needed
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

     // --- NEW: Helper function to update video-level button states ---
     function updateVideoButtonState(stepName, currentStatuses) {
        const button = document.querySelector(`#pipelineControlPanel button[data-action='${stepName}']`);
        if (!button) return; // Button might not exist if panel isn't rendered fully

        const currentStepStatus = currentStatuses[`${stepName}_status`] || 'Unknown';
        let prerequisitesMet = true;

        // Define prerequisites for each step
        const prereqs = {
            'audio': { 'download': 'Complete' },
            'transcript': { 'audio': 'Complete' },
            'diarization': { 'audio': 'Complete' }, // Video-level diarization
            'exchange_id': { 'transcript': 'Complete' }
        };

        if (prereqs[stepName]) {
            for (const prereqStep in prereqs[stepName]) {
                const requiredStatus = prereqs[stepName][prereqStep];
                const actualStatus = currentStatuses[`${prereqStep}_status`] || 'Pending';
                if (actualStatus !== requiredStatus) {
                    prerequisitesMet = false;
                    break;
                }
            }
        }

        // Button should be enabled if prerequisites are met AND the step is not currently running or queued
        const isIdle = !['Running', 'Queued'].includes(currentStepStatus);
        const shouldBeEnabled = prerequisitesMet && isIdle;

        button.disabled = !shouldBeEnabled;

         // Optional: Update button text/icon based on state (e.g., "Retry" on Error)
         const icon = button.querySelector('i');
         if (icon) {
             if (currentStepStatus === 'Error') {
                 icon.className = 'bi bi-arrow-repeat';
                 button.innerHTML = `<i class="bi bi-arrow-repeat"></i> Retry`;
             } else if (currentStepStatus === 'Complete') {
                 icon.className = 'bi bi-arrow-repeat';
                  button.innerHTML = `<i class="bi bi-arrow-repeat"></i> Re-run`;
             } else {
                 icon.className = 'bi bi-play-fill';
                 button.innerHTML = `<i class="bi bi-play-fill"></i> Run`;
             }
         }
    }

    // --- Index Page: Delete selection Logic ---
    // (Keep existing logic)
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
    // Run initial state update if on details page
    if (videoDetailsContainer && VIDEO_ID) {
        console.log("Setting initial button states on details page.");
        // Fetch initial statuses (could be embedded in HTML or via an initial AJAX call)
        // For now, let's assume Jinja sets the *very* initial state correctly,
        // and SSE will handle subsequent updates. If statuses change rapidly before
        // first SSE message, there might be brief inconsistency.
    }


    // Capitalize first letter helper
    String.prototype.capitalize = function() {
      return this.charAt(0).toUpperCase() + this.slice(1);
    }


}); // End DOMContentLoaded

// Function to map status to Bootstrap badge class (copied from old version)
function getStatusClass(status) {
    status = status ? status.toLowerCase() : 'unknown';
    switch (status) {
        case 'complete': return 'status-complete'; // Match CSS more closely
        case 'running': return 'status-running';
        case 'queued': return 'status-queued';
        case 'pending': return 'status-pending';
        case 'error': return 'status-error';
        case 'skipped': return 'status-skipped';
        case 'ready': return 'status-ready';
        case 'processing': return 'status-processing'; // Alias
        case 'completed with errors': return 'status-warning'; // Example for partial success
        default: return 'status-unknown';
    }
}

// --- END OF FILE: static/js/app.js ---