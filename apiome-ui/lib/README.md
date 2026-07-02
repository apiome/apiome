# UI Library

This library is used by the React application, providing mainly database-driven functionality.

It is located outside the main source directory, restricting direct application access.

## Auth

The `auth` directory contains authentication directives for `next-auth` sign-in functions.

| Name | Description |
| ---- | ----------- |
| `credentials.ts` | Credentials-based sign-in |

## Database

Contains database-related functionality.  This is direct access to the `pg` library, which is a thin layer
library.
