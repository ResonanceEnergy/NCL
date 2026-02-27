The following `ARCHITECTURE.md` provides a comprehensive overview of the NCL repository, its components, and operational characteristics, derived from the provided repository structure.

---

# ARCHITECTURE.md: NCL System Architecture Documentation

## 1. Executive Summary

The NCL (likely **Nodal Cluster Link** or **Network Control Layer**) system is designed as a focused monitoring and reporting solution. Its primary purpose is to collect, process, and visualize data from an external "matrix" of entities, providing insights into their status and performance through a dedicated web-based dashboard. The system leverages Python for its core logic, handling data acquisition, transformation, and persistence, while using static HTML for user-facing visualization.

NCL is structured to be self-contained, with clear separation of concerns for data collection, storage, and presentation. It includes mechanisms for automated deployment, configuration management, and robust logging, ensuring operational efficiency and maintainability. The overarching `NCC_Master_Doctrine_v2.0.md` suggests a foundational set of principles guiding its design and operation within a larger ecosystem.

This document outlines the architecture of the NCL system, detailing its key components, data flow, dependencies, and deployment strategy. It also addresses critical considerations such as security and performance, and provides a roadmap for future enhancements, aiming to facilitate understanding for developers, operators, and stakeholders alike.

## 2. System Overview

The NCL system primarily consists of a Python-based runner for data collection and processing, an orchestrator script, and an HTML dashboard for visualization. It interacts with an external "Matrix" source to gather data, stores this data locally, and presents it to users via a web interface.

```
+--------------------------------------------------------------------------------------------------------------------------------------+
|                                                            NCL System                                                                |
|                                                                                                                                      |
|  +---------------------------+       +------------------------------------+                                                        |
|  |     External "Matrix"     |       |          start_ncl.py            |                                                        |
|  |     Source (e.g., API,    |       |         (NCL Orchestrator)         |                                                        |
|  |      Sensors, Network)    |<----->|     Manages, Schedules, Configures   |                                                        |
|  +---------------------------+       +-------------------+----------------+                                                        |
|               ^                                          |                                                                         |
|               | Data Fetch                               | Commands / Status                                                       |
|               |                                          |                                                                         |
|  +-------------------------------------+                 |                                                                         |
|  |       matrix_monitor_runner.py      |<----------------+                                                                         |
|  |      (Data Collection & Processor)  |                                                                                           |
|  |                                     |                                                                                           |
|  +-------------------+-----------------+                                                                                           |
|                       |                                                                                                             |
|                       | Processed & Raw Data                                                                                        |
|                       |                                                                                                             |
|  +-------------------+-----------------+                                                                                           |
|  |    Data Storage (data/, dashboard_data/)                                                                                          |
|  |    - Raw data from runner                                                                                                        |
|  |    - Processed data for dashboard                                                                                                |
|  +-------------------+-----------------+                                                                                           |
|                       |                                                                                                             |
|                       | Dashboard Data                                                                                              |
|                       |                                                                                                             |
|  +-------------------+-----------------+                                                                                           |
|  |       matrix_monitor_dashboard.html |<---------------------------------------------------------------------------------------+   |
|  |        (Web-based Visualization)    |                                                                                         |   |
|  +-------------------+-----------------+                                                                                         |   |
|                       ^                                                                                                           |   |
|                       | HTTP Request                                                                                              |   |
|                       |                                                                                                           |   |
|  +-------------------+-----------------+                                                                                         |   |
|  |      User/Operator Browser          |                                                                                         |   |
|  +-------------------------------------+                                                                                         |   |
|                                                                                                                                   |   |
|  +-------------------------------------+                                                                                         |   |
|  |    Supporting Infrastructure        |                                                                                         |   |
|  |    - config/ (Configuration)        |                                                                                         |   |
|  |    - logs/ (System Logs)            |                                                                                         |   |
|  |    - reports/ (Generated Reports)   |                                                                                         |   |
|  |    - deploy.py (Deployment Utility) |                                                                                         |   |
|  +-------------------------------------+-----------------------------------------------------------------------------------------+   |
+--------------------------------------------------------------------------------------------------------------------------------------+
```

## 3. Component Breakdown

The NCL system is composed of several distinct modules, each responsible for a specific set of functionalities.

### 3.1 NCL Orchestrator (`start_ncl.py`)
This script serves as the main entry point and orchestrator for the NCL system. It is responsible for initializing the environment, loading configurations, and potentially scheduling or directly invoking other core components like the `matrix_monitor_runner.py`. It ensures that all necessary processes are started and managed correctly.

### 3.2 Matrix Monitor Runner (`matrix_monitor_runner.py`)
This is the core data collection and processing engine. Its responsibilities include:
*   **Data Acquisition:** Connecting to and fetching data from the external "Matrix" source.
*   **Data Processing:** Transforming raw data into a usable format, performing aggregations, calculations, or filtering.
*   **Data Persistence:** Storing processed and potentially raw data in the `data/` directory.
*   **Dashboard Data Preparation:** Preparing and storing specific datasets optimized for the `matrix_monitor_dashboard.html` in the `dashboard_data/` directory.
*   **Reporting:** Potentially generating reports into the `reports/` directory based on collected data.

### 3.3 Matrix Monitor Dashboard (`matrix_monitor_dashboard.html`)
This is the front-end component for visualizing the monitored "matrix" data.