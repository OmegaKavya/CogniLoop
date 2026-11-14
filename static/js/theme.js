/*
 * Theme switching.
 *
 * The stylesheet carries a full dark palette, but until the templates' colour
 * literals were migrated to tokens it could not be turned on without putting
 * white cards on a dark page. They have been migrated, so dark mode now
 * follows the reader's system preference and can be overridden per browser.
 *
 * The attribute itself is set by a small inline snippet in each page's <head>,
 * before first paint, so the page never flashes the wrong theme. This file
 * only adds the control and keeps it in sync.
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'cogniloop-theme';

  function stored() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      // Private browsing and blocked site data both throw here. Falling back to
      // the system preference is correct, so this is not an error.
      return null;
    }
  }

  function systemPrefersDark() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function active() {
    return document.documentElement.getAttribute('data-theme')
      || (systemPrefersDark() ? 'dark' : 'light');
  }

  function apply(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      // Preference simply will not persist; the page still switches.
    }
    update(theme);
  }

  var button = null;

  function update(theme) {
    if (!button) return;
    var dark = theme === 'dark';
    button.setAttribute('aria-pressed', String(dark));
    button.setAttribute('title', dark ? 'Switch to light theme' : 'Switch to dark theme');
    button.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
    button.textContent = dark ? '☀' : '☾';
  }

  function build() {
    var host = document.querySelector('.nav-links, .nav-buttons, .navbar');
    if (!host) return;

    button = document.createElement('button');
    button.type = 'button';
    button.className = 'theme-toggle';
    button.addEventListener('click', function () {
      apply(active() === 'dark' ? 'light' : 'dark');
    });
    update(active());
    host.appendChild(button);
  }

  // Track the system setting for as long as the reader has not chosen one.
  if (window.matchMedia) {
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    var onChange = function (e) {
      if (stored()) return;
      document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
      update(e.matches ? 'dark' : 'light');
    };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else {
    build();
  }
})();
