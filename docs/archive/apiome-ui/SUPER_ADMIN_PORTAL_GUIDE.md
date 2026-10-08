# Super Admin Portal - Implementation Guide

## Overview

A secure, password-protected super admin portal has been created for internal administration of Apiome. This portal provides a foundation for managing users, payments, system configuration, and more.

## 🔐 Security Features

- **Password Protection**: Simple password-based authentication
- **Session Management**: 8-hour session timeout
- **HTTP-Only Cookies**: Session tokens stored in secure cookies
- **401 Unauthorized**: Proper error responses for unauthorized access
- **Server-Side Validation**: All authentication checks happen server-side

## 🚀 Getting Started

### 1. Access the Admin Portal

Navigate to: `http://localhost:3000/admin`

### 2. Login Credentials

**Password**: The password is stored in your `.env` file:
```bash
ADMIN_PASSWORD=ApiomeAdmin2026!
```

**⚠️ IMPORTANT**: Change this password to something more secure before deploying to production!

### 3. First Login

1. Navigate to `/admin`
2. Enter the admin password
3. Click "Access Admin Portal"
4. You'll be redirected to the dashboard at `/admin/dashboard`

## 📁 File Structure

```
src/app/
├── admin/
│   ├── layout.tsx                    # Admin layout with auth check
│   ├── page.tsx                      # Admin landing page (redirects)
│   ├── AdminLoginClient.tsx          # Login form component
│   └── dashboard/
│       ├── page.tsx                  # Dashboard server component
│       └── AdminDashboardClient.tsx  # Dashboard UI component
├── api/
│   └── admin/
│       ├── auth/
│       │   └── route.ts              # Login/logout API endpoints
│       └── stats/
│           └── route.ts              # Example protected API endpoint
└── utils/
    └── adminAuth.ts                  # Server-side auth utility
```

## 🔑 Environment Configuration

### .env
```bash
# Admin password for super admin site (change this to a secure password)
ADMIN_PASSWORD=ApiomeAdmin2026!
```

### .env.example
```bash
# Admin password for super admin site
ADMIN_PASSWORD=your_secure_admin_password_here
```

## 🎨 Features

### Current Features

1. **Secure Login Page**
   - Dark theme matching admin aesthetic
   - Password input with validation
   - Error handling and feedback
   - Loading states
   - Return to main site link

2. **Admin Dashboard**
   - Stats overview (placeholder data)
   - Management menu with 5 main sections:
     - User Management
     - Payment Management
     - Database Administration
     - System Monitoring
     - System Configuration
   - Logout functionality
   - Session information

3. **Session Management**
   - 8-hour session duration
   - Automatic expiration
   - Secure cookie storage
   - Server-side validation

4. **Protected API Routes**
   - Example stats endpoint
   - 401 responses for unauthorized access
   - Easy to extend for additional endpoints

## 🛠️ Implementation Details

### Authentication Flow

1. **Login**:
   ```
   User enters password → POST /api/admin/auth
   → Validates against ADMIN_PASSWORD
   → Creates session cookie
   → Redirects to /admin/dashboard
   ```

2. **Protected Pages**:
   ```
   User visits /admin/dashboard
   → Server checks admin_session cookie
   → Validates token and expiration
   → Shows dashboard or redirects to login
   ```

3. **Logout**:
   ```
   User clicks logout → DELETE /api/admin/auth
   → Deletes session cookie
   → Redirects to /admin
   ```

### API Endpoints

#### POST /api/admin/auth
**Purpose**: Authenticate admin user

**Request**:
```json
{
  "password": "your_admin_password"
}
```

**Success Response** (200):
```json
{
  "success": true
}
```

**Error Response** (401):
```json
{
  "error": "Invalid password"
}
```

#### DELETE /api/admin/auth
**Purpose**: Logout admin user

**Success Response** (200):
```json
{
  "success": true
}
```

#### GET /api/admin/stats (Example)
**Purpose**: Get system statistics (requires authentication)

**Success Response** (200):
```json
{
  "totalUsers": 0,
  "activeUsers": 0,
  "totalRevenue": 0,
  "systemStatus": "healthy"
}
```

**Error Response** (401):
```json
{
  "error": "Unauthorized access",
  "message": "Admin authentication required"
}
```

## 📋 Next Steps

### Implement Real Functionality

The current implementation provides the structure and placeholders. To add real functionality:

#### 1. User Management

Create `/app/api/admin/users/route.ts`:
```typescript
export async function GET(request: NextRequest) {
  const isAuthenticated = await isAdminAuthenticated();
  if (!isAuthenticated) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  
  // Fetch users from your database
  const users = await fetchUsersFromDB();
  return NextResponse.json(users);
}
```

#### 2. Payment Management

Create `/app/api/admin/payments/route.ts`:
```typescript
export async function GET(request: NextRequest) {
  const isAuthenticated = await isAdminAuthenticated();
  if (!isAuthenticated) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  
  // Fetch payment data from Stripe/payment processor
  const payments = await fetchPayments();
  return NextResponse.json(payments);
}
```

#### 3. Create Management Pages

For each section, create a dedicated page:
- `/app/admin/dashboard/users/page.tsx`
- `/app/admin/dashboard/payments/page.tsx`
- `/app/admin/dashboard/database/page.tsx`
- etc.

### Example: User Management Page

```typescript
// /app/admin/dashboard/users/page.tsx
import { isAdminAuthenticated } from '@/app/utils/adminAuth';
import { redirect } from 'next/navigation';
import UsersClient from './UsersClient';

export default async function UsersPage() {
  const isAuthenticated = await isAdminAuthenticated();
  
  if (!isAuthenticated) {
    redirect('/admin');
  }
  
  // Fetch users from your API
  const users = await fetchUsers();
  
  return <UsersClient users={users} />;
}
```

## 🔒 Security Best Practices

### Production Deployment

1. **Change the Admin Password**
   ```bash
   # Generate a strong password
   openssl rand -base64 32
   
   # Update .env
   ADMIN_PASSWORD=your_generated_secure_password
   ```

2. **Use Environment-Specific Passwords**
   - Different passwords for development, staging, production
   - Store production password in your hosting platform's secrets manager

3. **Consider Enhanced Authentication**
   - Add JWT tokens instead of simple session cookies
   - Implement rate limiting on login attempts
   - Add 2FA (Two-Factor Authentication)
   - Use OAuth for admin users

4. **Add Logging**
   - Log all admin logins
   - Log all admin actions
   - Monitor for suspicious activity

5. **HTTPS Only**
   - Ensure the site runs on HTTPS in production
   - Set secure cookie flags appropriately

### Recommended Enhancements

1. **Add IP Whitelisting**
   ```typescript
   // In middleware or auth check
   const allowedIPs = ['your.ip.address'];
   const clientIP = request.headers.get('x-forwarded-for');
   if (!allowedIPs.includes(clientIP)) {
     return unauthorized();
   }
   ```

2. **Implement Audit Logging**
   ```typescript
   async function logAdminAction(action: string, userId: string) {
     await db.auditLog.create({
       action,
       userId,
       timestamp: new Date(),
       ip: request.ip,
     });
   }
   ```

3. **Add Rate Limiting**
   ```typescript
   import rateLimit from 'express-rate-limit';
   
   const limiter = rateLimit({
     windowMs: 15 * 60 * 1000, // 15 minutes
     max: 5, // 5 attempts
   });
   ```

## 🎨 Customization

### Styling

The admin portal uses a dark theme with red accents. To customize:

- **Primary Color**: Currently red (#DC2626) - change in Tailwind classes
- **Background**: Dark gray gradient
- **Accent Color**: Can be changed by replacing `bg-red-600`, `text-red-400`, etc.

### Adding New Admin Sections

1. Create a new MenuItem in `AdminDashboardClient.tsx`
2. Create the corresponding page in `/app/admin/dashboard/[section]/`
3. Create API endpoints in `/app/api/admin/[section]/`
4. Add navigation and routing

## 📊 Testing

### Manual Testing Checklist

- [ ] Can access `/admin` without authentication
- [ ] Login with correct password succeeds
- [ ] Login with incorrect password fails with 401
- [ ] Dashboard displays after successful login
- [ ] Logout works and redirects to login
- [ ] Session expires after 8 hours
- [ ] Protected API endpoints return 401 when not authenticated
- [ ] Protected API endpoints work when authenticated

### Testing Unauthorized Access

```bash
# Should return 401
curl -X GET http://localhost:3000/api/admin/stats

# Login first
curl -X POST http://localhost:3000/api/admin/auth \
  -H "Content-Type: application/json" \
  -d '{"password": "your_password"}' \
  -c cookies.txt

# Should work with session cookie
curl -X GET http://localhost:3000/api/admin/stats -b cookies.txt
```

## 🚀 Deployment

### Environment Variables

Ensure these are set in your production environment:
- `ADMIN_PASSWORD` - Strong, unique password
- `NODE_ENV=production` - Enables secure cookies

### Deployment Checklist

- [ ] Change admin password in production
- [ ] Enable HTTPS
- [ ] Set secure cookie flags
- [ ] Configure CORS if needed
- [ ] Set up monitoring and logging
- [ ] Test all authentication flows
- [ ] Document password management process

## 📝 Additional Notes

- The current implementation is intentionally simple for internal use
- For production use with multiple admins, consider a proper user management system
- The session token is basic - consider JWT for production
- All placeholder data (stats, user counts) should be connected to your backend
- Consider adding email notifications for admin actions

## 🆘 Troubleshooting

### "Cannot find module" errors
Make sure all files are created and imports are correct.

### Session not persisting
Check that cookies are enabled and the domain matches.

### 401 errors on dashboard
Session may have expired. Clear cookies and login again.

### Password not working
Check the `.env` file and ensure the dev server was restarted.

---

**Built for Apiome Internal Administration**
*Last Updated: December 5, 2024*

