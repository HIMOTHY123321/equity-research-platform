# Equity Research Platform

A full-stack equity research platform built to organize market data, identify technical setups, compare historical market behavior, and present evidence-based decision states in a single research workflow.

The project focuses on making market analysis more structured and explainable rather than generating arbitrary scores or simple buy/sell signals.

## Overview

The platform combines live and historical market data with deterministic research tools for:

- Market structure analysis
- Support and resistance detection
- Technical setup identification
- Historical analog comparison
- Market context and session analysis
- Evidence-based decision states
- Research validation
- Watchlists and alerts
- Multi-user authentication

The system is designed so that research outputs can be traced back to the underlying market evidence.

## Core Features

### Market Structure

The platform detects swing highs, swing lows, pivots, break states, and other structural market behavior.

### Setup Detection

Several rule-based market setups are supported, including:

- Resistance rejection
- Support reclaim
- Gap continuation
- Gap fill
- Trend pullback
- Breakout retest
- Failed breakout

Setups are generated through deterministic conditions rather than AI-generated predictions.

### Historical Analog Engine

Current market conditions can be compared against similar historical setups.

The research system analyzes factors such as:

- Forward price behavior
- Maximum favorable excursion
- Maximum adverse excursion
- First-hit outcomes
- Setup decay
- Stability
- Concentration
- Historical similarity

Historical analysis is designed with anti-lookahead protections so future information does not influence past research states.

### Decision Engine

Instead of generic BUY / SELL ratings, the system tracks the state of a market thesis.

Example states include:

`WATCHING`

`ENTRY CONDITIONS MET`

`ACTIVE THESIS`

`THESIS STRENGTHENING`

`THESIS WEAKENING`

`INVALIDATED`

`EXIT CONDITIONS MET`

`EXPIRED`

`ABSTAIN`

These states are based on deterministic market conditions and research evidence.

## Real-Time Market Data

The platform includes a provider abstraction that separates:

- Historical market data
- Latest available quotes
- Streaming market data

The current research environment integrates Twelve Data and Yahoo Finance.

Historical data and fallback data can come from Yahoo Finance, while supported streaming symbols can use Twelve Data WebSocket ingestion.

The interface only labels data as **REAL TIME** when a genuine fresh streaming event has been received from an authorized provider connection.

Fallback or delayed data is never presented as real-time.

## Research Integrity

A major goal of the project is preventing misleading research results.

The research pipeline includes protections for:

- Lookahead bias
- Historical state contamination
- Future pivot information
- Provider provenance
- Final-bar setup evaluation
- Research evidence freezing
- Data validation
- Signal validation
- Historical outcome separation

Historical research distinguishes between what was known at the time and what happened afterward.

## Architecture

```text
Market Data
    ↓
Feature Engine
    ↓
Market Structure
    ↓
Support / Resistance
    ↓
Setup Detectors
    ↓
Research Lab
    ↓
Decision Engine
    ↓
API
    ↓
Web Dashboard
