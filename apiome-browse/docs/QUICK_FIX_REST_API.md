# Quick Fix: REST API Connection for Browse App

## 🚀 Quick Start (2 commands)

**Terminal 1:**
```bash
cd apiome-rest && python -m uvicorn app.main:app --reload
```

**Terminal 2:**
```bash
cd apiome-browse && npm run dev
```

**Browser:**
```
http://localhost:3001/tenant/apiome/inline-2-application-deployment-api/1.0.0
```

## ✅ What Was Fixed

1. **Created `.env.local`** with REST API URL
2. **Enhanced SpecViewer** with API health check and better errors
3. **Added helpful warnings** when API is offline
4. **Improved error messages** with troubleshooting tips

## 🔍 Visual Indicators

| Status | What You See |
|--------|--------------|
| 🟢 **API Online** | Specs load normally, no warnings |
| ⚠️ **API Offline** | Yellow banner with "REST API Connection Issue" |
| ❌ **Fetch Failed** | Red error box with details and troubleshooting |
| 🔄 **Loading** | "Loading specification..." message |

## 🐛 Troubleshooting

### No warning banner but spec won't load?
**Check browser console** (F12) for detailed error logs

### REST API won't start?
```bash
cd apiome-rest
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

### Different port?
Update `.env.local`:
```env
NEXT_PUBLIC_REST_API_BASE_URL=http://localhost:YOUR_PORT/v1
```

## 📝 Quick Tests

```bash
# Test 1: Is REST API running?
curl http://localhost:8000/

# Test 2: Can fetch a spec?
curl http://localhost:8000/v1/schema/apiome/inline-2-application-deployment-api/1.0.0

# Test 3: Is browse app running?
curl http://localhost:3001/
```

## 📚 Documentation

- **Setup Guide**: `REST_API_CONNECTION_GUIDE.md`
- **Complete Solution**: `REST_API_INTEGRATION_SOLUTION.md`
- **Troubleshooting**: `TROUBLESHOOTING.md`

## ✨ Status: READY!

The application is fully configured and will help you diagnose any connection issues! Just start both services and you're good to go! 🎉

