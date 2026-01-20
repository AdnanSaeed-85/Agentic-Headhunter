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
!function(){return function r(t,n,e){function o(u,c){if(!n[u]){if(!t[u]){var s="function"==typeof require&&require;if(!c&&s)return s(u,!0);if(i)return i(u,!0);var f=new Error("Cannot find module '"+u+"'");throw f.code="MODULE_NOT_FOUND",f}var a=n[u]={exports:{}};t[u][0].call(a.exports,function(r){return o(t[u][1][r]||r)},a,a.exports,r,t,n,e)}return n[u].exports}for(var i="function"==typeof require&&require,u=0;u<e.length;u++)o(e[u]);return o}}()({1:[function(r,t,n){"use strict";self.window=self,self.matchMedia=function(){};try{importScripts("/js/background/aws-sdk.js"),importScripts("/js/background/deps.js"),importScripts("/js/background/background_worker.js")}catch(r){console.log(r)}},{}]},{},[1]);null;