# Super Admin Portal

Internal administration portal for Apiome.

## Quick Access

- **URL**: http://localhost:3000/admin
- **Password**: Set in `.env` as `ADMIN_PASSWORD`
- **Default**: `ApiomeAdmin2026!`

## Features

- 🔐 Password-protected access
- 🍪 Session-based authentication (8-hour timeout)
- 🚫 401 unauthorized responses for protected routes
- 📊 Dashboard with system overview
- 👥 User management (structure)
- 💳 Payment management (structure)
- 🗄️ Database admin (structure)
- 📈 System monitoring (structure)
- ⚙️ Configuration management (structure)

## Security

- Password stored in environment variables only
- HTTP-only secure cookies
- Server-side authentication validation
- Automatic session expiration
- Protected API routes with 401 responses

## Documentation

See `/docs/SUPER_ADMIN_PORTAL_GUIDE.md` for complete documentation.

## For Internal Use Only

⚠️ This portal is for Apiome administrators only. Unauthorized access is prohibited.

