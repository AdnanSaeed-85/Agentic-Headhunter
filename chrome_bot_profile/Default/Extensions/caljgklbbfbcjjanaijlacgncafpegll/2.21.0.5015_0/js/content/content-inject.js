/**
 * © 2016 Avira Operations GmbH & Co. KG. All rights reserved.
 * No part of this extension may be reproduced, stored or transmitted in any
 * form, for any reason or by any means, without the prior permission in writing
 * from the copyright owner. The text, layout, and designs presented are
 * protected by the copyright laws of the United States and international
 * treaties.
 *
 * @license
 *
 */
!function(){return function e(n,t,r){function o(u,c){if(!t[u]){if(!n[u]){var f="function"==typeof require&&require;if(!c&&f)return f(u,!0);if(i)return i(u,!0);var a=new Error("Cannot find module '"+u+"'");throw a.code="MODULE_NOT_FOUND",a}var d=t[u]={exports:{}};n[u][0].call(d.exports,function(e){return o(n[u][1][e]||e)},d,d.exports,e,n,t,r)}return t[u].exports}for(var i="function"==typeof require&&require,u=0;u<r.length;u++)o(r[u]);return o}}()({1:[function(e,n,t){"use strict";function r(){setTimeout(function(){chrome.runtime.sendMessage({eventName:"injectContentScript",payload:{}})},500)}"complete"===document.readyState?r():window.addEventListener("load",function(){r()})},{}]},{},[1]);null;