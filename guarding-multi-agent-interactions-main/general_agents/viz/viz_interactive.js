/**
 * Interactive DIG Visualization - Edge Highlighting
 * 
 * This script handles hover interactions for the DIG visualization:
 * - Event nodes: Highlights incoming (blue) and outgoing (orange) edges
 * - Activation nodes: Highlights covered edges (red) and dashed edges (orange)
 */

// Global configuration - will be set by Python when generating HTML
let edgeIdToTraceIndex = {};
let numEdges = 0;
let originalEdgeColors = [];
let originalEdgeWidths = [];
let originalEdgeDashes = [];

function initializeEdgeHighlighting(edgeMapping, totalEdges) {
    edgeIdToTraceIndex = edgeMapping;
    numEdges = totalEdges;
    
    const plotDiv = document.getElementsByClassName('plotly-graph-div')[0];
    
    // Store original edge styles for restoration
    for (let i = 0; i < numEdges; i++) {
        const trace = plotDiv.data[i];
        if (trace && trace.line) {
            originalEdgeColors.push(trace.line.color || 'rgba(150,150,150,0.3)');
            originalEdgeWidths.push(trace.line.width || 1);
            originalEdgeDashes.push(trace.line.dash || 'solid');
        } else {
            originalEdgeColors.push('rgba(150,150,150,0.3)');
            originalEdgeWidths.push(1);
            originalEdgeDashes.push('solid');
        }
    }
    
    // Handle hover events
    plotDiv.on('plotly_hover', function(eventData) {
        const point = eventData.points[0];
        
        // Check if hovering over a node
        if (point.customdata && point.customdata[0]) {
            try {
                const nodeData = JSON.parse(point.customdata[0]);
                
                // Handle event node hover
                if (nodeData.type === 'event') {
                    highlightEventEdges(plotDiv, nodeData);
                }
                // Handle activation node hover
                else if (nodeData.type === 'activation' && nodeData.covered_edges) {
                    highlightActivationEdges(plotDiv, nodeData);
                }
            } catch (e) {
                console.error('Error handling hover:', e);
            }
        }
    });
    
    // Handle unhover events
    plotDiv.on('plotly_unhover', function() {
        resetEdges(plotDiv);
    });
}

/**
 * Highlight edges for event node hover
 * - Incoming edges: blue
 * - Outgoing edges: orange
 */
function highlightEventEdges(plotDiv, nodeData) {
    const incomingEdges = new Set(nodeData.incoming_edges || []);
    const outgoingEdges = new Set(nodeData.outgoing_edges || []);
    
    const lineColors = [];
    const lineWidths = [];
    const traceIndices = [];
    
    for (let i = 0; i < numEdges; i++) {
        const edgeId = Object.keys(edgeIdToTraceIndex).find(key => edgeIdToTraceIndex[key] === i);
        
        if (edgeId && incomingEdges.has(edgeId)) {
            // Incoming edges: blue
            lineColors.push('rgba(0, 0, 255, 0.8)');
            lineWidths.push(3);
        } else if (edgeId && outgoingEdges.has(edgeId)) {
            // Outgoing edges: orange
            lineColors.push('rgba(255, 140, 0, 0.8)');
            lineWidths.push(3);
        } else {
            // Default dim
            lineColors.push('rgba(200, 200, 200, 0.1)');
            lineWidths.push(0.5);
        }
        traceIndices.push(i);
    }
    
    Plotly.restyle(plotDiv, {
        'line.color': lineColors,
        'line.width': lineWidths
    }, traceIndices);
}

/**
 * Highlight edges for activation node hover
 * - Covered edges (solid, from backward traversal): red
 * - Dashed edges (directly connected but not traversed): orange
 */
function highlightActivationEdges(plotDiv, nodeData) {
    const coveredEdges = new Set(nodeData.covered_edges);
    const dashedEdges = new Set(nodeData.dashed_edges || []);
    
    const lineColors = [];
    const lineWidths = [];
    const traceIndices = [];
    
    for (let i = 0; i < numEdges; i++) {
        const edgeId = Object.keys(edgeIdToTraceIndex).find(key => edgeIdToTraceIndex[key] === i);
        
        if (edgeId && coveredEdges.has(edgeId)) {
            // Highlight covered edges (backward traversal through solid edges)
            lineColors.push('rgba(255, 0, 0, 0.8)');
            lineWidths.push(3);
        } else if (edgeId && dashedEdges.has(edgeId)) {
            // Highlight dashed edges (directly connected but not traversed)
            lineColors.push('rgba(255, 165, 0, 0.8)');
            lineWidths.push(3);
        } else {
            // Dim uncovered edges
            lineColors.push('rgba(150, 150, 150, 0.1)');
            lineWidths.push(1);
        }
        traceIndices.push(i);
    }
    
    Plotly.restyle(plotDiv, {
        'line.color': lineColors,
        'line.width': lineWidths
    }, traceIndices);
}

/**
 * Reset all edges to their original appearance (colors set by Python)
 */
function resetEdges(plotDiv) {
    const traceIndices = Array.from({length: numEdges}, (_, i) => i);
    
    Plotly.restyle(plotDiv, {
        'line.color': originalEdgeColors,
        'line.width': originalEdgeWidths,
        'line.dash': originalEdgeDashes
    }, traceIndices);
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Edge mapping will be injected by Python
    // initializeEdgeHighlighting will be called from inline script
});
