/**
 * CogniLoop Client Security & Anti-Inspection Module
 * Built by Kavya Aggarwal | IEEE Research Project
 * 
 * Protects frontend interface demonstrations by restricting context menus,
 * inspection developer tool shortcuts, and source code enumeration.
 */

(function() {
    'use strict';

    // 1. Block Right-Click Context Menu
    document.addEventListener('contextmenu', function(e) {
        e.preventDefault();
        return false;
    }, false);

    // 2. Block Developer Tools & View Source Keyboard Shortcuts
    document.addEventListener('keydown', function(e) {
        // F12 (DevTools)
        if (e.key === 'F12' || e.keyCode === 123) {
            e.preventDefault();
            return false;
        }
        // Ctrl+Shift+I or Cmd+Option+I (Open DevTools Inspect)
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'I' || e.key === 'i' || e.keyCode === 73)) {
            e.preventDefault();
            return false;
        }
        // Ctrl+Shift+J or Cmd+Option+J (Open DevTools Console)
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'J' || e.key === 'j' || e.keyCode === 74)) {
            e.preventDefault();
            return false;
        }
        // Ctrl+Shift+C or Cmd+Option+C (Inspect Element Selector)
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'C' || e.key === 'c' || e.keyCode === 67)) {
            e.preventDefault();
            return false;
        }
        // Ctrl+U or Cmd+U (View Source Code)
        if ((e.ctrlKey || e.metaKey) && (e.key === 'U' || e.key === 'u' || e.keyCode === 85)) {
            e.preventDefault();
            return false;
        }
        // Ctrl+S or Cmd+S (Save Webpage Local Copy)
        if ((e.ctrlKey || e.metaKey) && (e.key === 'S' || e.key === 's' || e.keyCode === 83)) {
            e.preventDefault();
            return false;
        }
    }, false);

    // 3. Anti-Debugging / Inspector Halt Trap
    // When Developer Tools are opened via browser menu, this loop halts console execution
    setInterval(function() {
        var start = performance.now();
        (function() {
            return false;
        }
        ["constructor"]("debugger")
        ());
        var end = performance.now();
        // If execution took significantly longer than 100ms, debugger was likely paused/active
        if (end - start > 100) {
            document.body.style.display = 'none';
        } else {
            if (document.body && document.body.style.display === 'none') {
                document.body.style.display = '';
            }
        }
    }, 1000);

    // 4. Disable drag-and-drop of page media/assets
    document.addEventListener('dragstart', function(e) {
        if (e.target.nodeName === 'IMG' || e.target.nodeName === 'A') {
            e.preventDefault();
            return false;
        }
    }, false);

})();
