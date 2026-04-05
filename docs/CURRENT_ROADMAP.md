# Current Roadmap for Objectified

This document outlines the current roadmap for Objectified, along with the products and features planned for
development over the coming months.

## Problem Statement

Organizations have no problems visualizing and understanding their schema data when designed by data
scientists or SQL experts.

How do you visualize the data?  You use tools like Microsoft Access, dbForge Studio, DBeaver, dbVisualizer,
or even spreadsheets.

But that covers the visual.

How do you modify the schema?  How do you improve it?

"Text Editors are all you need".  Fine.  Use GitHub and GitLab to store your changes, and granted, you can
collaborate on changes.  And keep history, and run diffs.

How about a visual tool?  What exists?  There are tools like MySQL Workbench, pgAdmin, and others that
offer some visual schema design capabilities.  But they are limited in scope, and often tied to
specific database systems.

The question remains: "we've developed the schema, but how do we host it".  Similarly, "how do we publish it
in a central location for all users to access"?

Yes, you can use local systems like Backstage, GitHub Gist, GitLab Snippets, GitHub Pages, etc.  But the
problem remains.  You can host the schema, but how do you manage it?  How do you ensure quality?  How do you
ensure that the schema is up to date?

## Problem Solution

Objectified aims to solve these problems by providing a comprehensive platform for visualizing, modifying,
managing, publishing, and applying database schemas.  It will offer a user-friendly interface for designing 
schemas, along with robust collaboration features, version control integration, and support for multiple database systems.

Data design comes at a cost: you have to edit the data model, publish it, test it, deploy it, and check
it for errors.  Any errors need to go through the same process: open the file using your favorite text editor,
modify the schema, publish, test, ad nauseum.

Objectified's toolkit provides an ORM that allows you to define your schema in a visual editor.  From here,
you can manage the schema using version control, collaborate with team members, view history, run diffs,
store your schema, and publish it both publicly and allow selective private access using an API Key.

Our tag lines:

"GitHub and GitLab for your code.  Objectified for your Schemas."

And:

"Objectified: your data designed, defined, discovered."

Objectified provides a single source of truth for your schemas and your OpenAPI designs.  Think of it as a
SwaggerHub for your full service schema deployment.

SwaggerHub provides Swagger 2.0 publishing.\
SchemaHub provides JSON Schema publishing.

Objectified provides the rest, and gives you the tools to remain the best.

# Architecture

Objectified uses a modular architecture, providing wide scale access to the system through tenants,
projects, versions, and data instances.  Most records are tied to a version, which ties multiple releases
of schemas and modified versions of data to a master project.

Login security is provided using SSO and planned 2FA.

Current support is handled through GitHub and GitLab, as this is the most common method of login provider
access.  See GitHub Issues for more information, and see other `FEATURE_ROADMAP_*.md` documents for more
fine-detailed information.

Code is hosted in GitHub in a private repository.  Project tickets and issues are stored in GitHub issues.
No code is currently open sourced, however, this may change given market conditions and/or customer demand.

# Products

This is an outline of the current products.

Any products marked "In progress" are currently under development.

Products without any marking are either planned for future development, or are under consideration.

## Objectified: Studio (In progress)

Fully visual schema design tool from start to finish, offering a canvas to visually create ultra complex
schemas with ease.

Create classes, define properties, set relationships, define inheritance and composition all visually.

Generate resulting code for your schema through the Objectified platform: output OpenAPI, Arazzo, JSON Schemas.
Generate DDLs for SQL databases, Protobuf definitions, Kafka Schemas, and much more.

Host schemas for the world to see, or keep them private for your team.

## Objectified: API Designer (In progress)

A fully visual API designer tool that allows for the definition of paths and endpoints for both OpenAPI
and Arazzo API definitions.

Uses the already defined Schemas from Objectified Studio and applies them to project versions for easy
extensibility of the API design.

## Objectified: Self-Hosted

Do what you can do with Studio, but hosted on your own hardware.  Distribute it as you like within your
network, since all code is run in a Docker environment.  Set up Kubernetes and nginx instances to host
your own services in a round-robin fashion for high availability.

License Objectified to get access to a hosted Docker repository that contains all of the updates to the
code in line with the public release.  Choose to update from the beta or stable channels.  Code is pushed
as long as the company license is active.

## Objectified: Personal Edition

Do the same as Self-Hosted, but run locally.  Self-contained in its own unit, installed using Docker,
ready to deploy in minutes.

## Objectified: Database

A fully featured database system designed to store and manage data using the Objectified schemas defined in
your projects.

Automatically keeps the data up to date with the latest schema changes, ensures data integrity, and provides
discoverability features to easily find and access your data.

Fully automated backup and recovery options, along with robust security features to protect your data.  All
data is vectorized so it can easily be applied to an AI search engine, hosted by Objectified.

Uses a combination of PostgreSQL and Mongo to store snapshots of data, along with change logs and time-based
record keeping for auditing purposes.

## Objectified: Data ETL

A huge assortment of tools, along with an API library to extract, transform, and load data into the
Objectified database.  Fully automated, running in batches on a schedule, running as a stream or on demand,
with support for a wide variety of data sources and destinations.

All data is transformed to match Objectified schemas, and matched against the latest versions of each project
for which the data is loaded.

## Objectified: Schema Quality

Sets of data governance and quality tools to ensure that your schemas are up to date, follow best practices,
and are free from errors.

Run tests against your data, provide data scenarios, and receive reports on schema quality, tracking the
quality metrics over time as versions improve.

## Objectified: Data Discovery

Automated data discovery tools to help you find and access your data quickly and easily.  Search using
natural language queries, filter results based on various criteria, and visualize data relationships
to gain insights into your data.

Data discovery tasks can include things like discovering links between common fields of data between other
data sets in a tenant's schema.  For instance, records that contain email addresses can be automatically
linked and discovered using this system.  As long as schemas use the common property definitions, data
can be discovered automatically, and can be reported later for review.

Discovered data links can be accepted or rejected by data stewards, and can be used to create new relationships
between data sets.  These relationships can then be explored in a dry run environment before the data link is
accepted into the main schema.

Data links are defined as t1/t2/t3 relationships, where "t1" is the source data, "t2" is the target data,
and "t3" is the relationship type.  For example, "CustomerEmail" in "CustomerData" links to "EmailAddress"
in "MarketingData" as a "ContactPoint" relationship.

## Objectified: Data Enrichment

Automatically enrich your datasets using AI tools, and access to other services using MCP, or other
registered datasets within the Objectified data space.  Publicly available datasets can be used to
enrichen your data, private datasets also can be accessed via API Keys, with access agreements from
other tenant providers.

Enrichment providers can also be provided by third party services, such as Clearbit, FullContact, and others.
These include things like geolocation services (via Precisely, RMS, AIR, etc.), government GIS data
sources, WHOIS and DNS data sources, IP geolocation data sources, and more.  All of which can be run
asynchronously to enrich your data before loading it into the Objectified database.  All of which are
available via licensing agreements.

## Objectified: Data Extraction

Data extraction tools to pull data from various sources, including databases, APIs, files, and more, including
but not limited to mainframe stores, legacy systems (ISO-based data, EDI data, etc.) and modern data sources.

## Objectified: Data Explorer

Similar to the design of applications like dbVisualizer and DBeaver, Objectified Data Explorer provides a
visual interface to explore your data stored in the Objectified database.  Browse tables, view relationships,
run queries, and visualize data in various formats.

Through these tools, users can dig into data records, view relationships at varying levels, and can explore
other various aspects of data through visual means.

## Objectified: Data Transformation

A large set of data transformation tools, all AI assisted, to clean, normalize, and enrich your data
before loading it into the Objectified database, keeping your data free from errors.

## Objectified: Data Hosting

Host your database with Objectified, providing high availability, scalability, and security for your data.
Backups are automated and kept as long as your hosting plan is active.  Select from different backup scenarios
ranging from hourly, daily, weekly, and monthly backups.  Plans are available based on data size and
access requirements.

## Objectified: Data Compliance

Compliance suites to ensure that your data meets various regulatory requirements, including GDPR, CCPA, HIPAA, and more.
Automated tools to scan your data, identify sensitive information, and provide reports on compliance status.

All of these cover data governance rules, which can be visually defined using the Objectified Rules engine.
This system will most likely use a system like Open Policy Agent (OPA) to define the rules, and then apply them
to the data stored in the Objectified database.  Since the data is stored in MongoDB snapshots, the
rules can be applied in batches, and against historical data.

The rules engine will most likely be a system like Temporal, Cadence, or similar, to allow for
asynchronous processing of data governance rules.

## Objectified: Browser

Publicly available catalog of browsable Schemas and full stack data definitions.  Uses a REST interface to
provide access to all public schemas, with options for private access using API Keys.

## Objectified: Auditor

Auditor is a fully functional database query search system that allows for time-based querying of data
with results that show the data as it existed at any point in time.  This data has a target retrieval
time of a maximum of 7 seconds between query and result, regardless of the size of the data.  The data
size is controlled by the user using a window, based on their data access plans.

Guarantees are only granted on higher level plans.  Lower level plans can have "best effort" queries, and
some can be performed as a batch that can then be retrieved when ready through a retrieval system.

## Objectified: Audit Actions

Automated actions can take place when an audit-level event occurs.  These actions are similar to Amazon's
Lambda functions, but are tied to data events.  For example, when a data instance is created, an action
can be triggered to notify a user, or to run a data quality check, or to enrich the data using AI services.

Other actions can be similar to taking corrective action when a database access level change occurs,
when a badge access is granted or revoked, when a schema is modified, and more.  All of these actions
trigger mechanisms that have ways to inform other people that an action or breached event has occurred.

Actions are defined using a visual editor, and include things like a Slack message, a PagerDuty notification,
DataDog log, etc.

### Languages

Objectified is written in TypeScript, using the latest NextJS library.  The UI uses elements from Radix UI
and components from Material UI.  Icons are provided by Lucide Icons, and some are SVG custom made.

Objectified Browser uses NextJS.

Objectified REST services are written using Python and FastAPI.

Objectified MCP services are written using Python and FastMCP.

Objectified AI services are written using Python, FastAPI, and Ollama models.

Ollama Models change quickly, and are configurable for AI responses in the Objectified platform, so the names
of the models will not be included in this document, as they change frequently.

### Databases

Database components are written using PostgreSQL and loaded using schema evolution manager tools.

Data snapshots are stored using MongoDB, which only stores delta copies of data for each version change,
so time-based access is possible without massive storage requirements.  Latest snapshots are stored in the
PostgreSQL database, vectorized, and quickly searchable.  Snapshots represent the current version of the
stored instances.

### Hostnames

`*.objectified.dev` is the main hostname for all Objectified design services (design being the Studio
components.)

`*.obj-db.com` is the hosted database services.  These still use Objectified design services for schema,
but the management is done using the `objectified.dev` domain.  `obj-db.com` is strictly for database
access via ETL, REST API, MCP, AI Services, and direct SQL object query services.

## Copyrights

No code uses proprietary code.  All code uses Open Source elements.

Objectified is Copyright 2018-2026, NobuData, LLC.
All rights reserved.
