const { spawn } = require('child_process');
const http = require('http');

const PORT = 3002;
const BASE_URL = `http://localhost:${PORT}`;
const MOCK_PORT = 3003;

const paths = [
  '/naviera',
  '/naviera/login',
  '/naviera/track',
  '/naviera/track/123',
  '/naviera/dashboard',
  '/naviera/shipments',
  '/naviera/settings',
];

function startMockServer(port) {
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Headers', '*');
    res.setHeader('Access-Control-Allow-Methods', '*');

    if (req.method === 'OPTIONS') {
      res.statusCode = 204;
      res.end();
      return;
    }

    if (req.url.startsWith('/api/v1/tracking/')) {
      res.statusCode = 200;
      res.end(JSON.stringify({
        "tracking_id": "123",
        "status": "IN_TRANSIT",
        "current_location": "Warehouse A",
        "estimated_delivery": "2026-07-01T12:00:00Z",
        "timeline": [
          { "timestamp": "2026-06-28T12:00:00Z", "status_title": "Order Placed", "message": "Order was received." }
        ],
        "package_details": []
      }));
      return;
    }

    if (req.url.startsWith('/api/v1/tenants/') && req.url.endsWith('/public')) {
      const parts = req.url.split('/');
      const slug = parts[4];
      res.statusCode = 200;
      res.end(JSON.stringify({
        id: `${slug}-id`,
        name: slug.charAt(0).toUpperCase() + slug.slice(1),
        slug: slug,
        settings: {
          brand: { primary_color: "#2563eb", secondary_color: "#1e40af" },
          landing_page: {
            blocks: [
              {
                type: "hero",
                content: {
                  title: `Welcome to ${slug}`,
                  subtitle: "Enterprise Multi-Tenant Logistics."
                }
              }
            ]
          }
        }
      }));
      return;
    }

    res.statusCode = 404;
    res.end(JSON.stringify({ error: "Not Found" }));
  });

  return new Promise((resolve) => {
    server.listen(port, () => {
      console.log(`Mock backend server running on port ${port}`);
      resolve(server);
    });
  });
}

async function main() {
  console.log(`Starting mock backend server on port ${MOCK_PORT}...`);
  const mockServer = await startMockServer(MOCK_PORT);

  console.log(`Starting Next.js dev server on port ${PORT}...`);
  
  // Use spawn to run 'npx next dev -p 3002'
  const devServer = spawn('npx', ['next', 'dev', '-p', PORT.toString()], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      PORT: PORT.toString(),
      BACKEND_API_URL: `http://localhost:${MOCK_PORT}`
    },
  });

  let serverStderr = '';
  devServer.stderr.on('data', (data) => {
    serverStderr += data.toString();
  });

  // Register clean shutdown on exit
  const cleanup = () => {
    console.log('Shutting down dev server...');
    devServer.kill('SIGINT');
    console.log('Shutting down mock server...');
    mockServer.close();
  };

  process.on('exit', cleanup);
  process.on('SIGINT', () => {
    cleanup();
    process.exit(1);
  });
  process.on('SIGTERM', () => {
    cleanup();
    process.exit(1);
  });

  try {
    // Poll the server until it is ready (up to 30 seconds)
    await pollServer(`${BASE_URL}/naviera`, 30000, 1000);
    console.log('Server is up! Starting smoke tests...');

    let failed = false;
    for (const path of paths) {
      const result = await checkPath(path);
      if (result.ok) {
        console.log(`✅ [PASS] ${path} - Status: ${result.status}`);
      } else {
        failed = true;
        if (result.error) {
          console.error(`❌ [FAIL] ${path} - Error: ${result.error}`);
        } else {
          console.error(`❌ [FAIL] ${path} - Status: ${result.status} (Expected 2xx or 3xx)`);
        }
      }
    }

    // Explicitly cleanup
    cleanup();
    process.off('exit', cleanup);

    if (failed) {
      console.error('Smoke tests failed.');
      process.exit(1);
    } else {
      console.log('All smoke tests passed successfully.');
      process.exit(0);
    }
  } catch (err) {
    console.error('Error during smoke tests:', err.message);
    if (serverStderr) {
      console.error('Server stderr output:\n', serverStderr);
    }
    cleanup();
    process.off('exit', cleanup);
    process.exit(1);
  }
}

function pollServer(url, timeoutMs, intervalMs) {
  const startTime = Date.now();
  return new Promise((resolve, reject) => {
    const timer = setInterval(() => {
      if (Date.now() - startTime > timeoutMs) {
        clearInterval(timer);
        reject(new Error(`Timeout waiting for server to start at ${url}`));
        return;
      }

      const req = http.get(url, (res) => {
        // Any response means server is listening
        clearInterval(timer);
        resolve();
      });

      req.on('error', () => {
        // Keep polling
      });

      req.end();
    }, intervalMs);
  });
}

function checkPath(path) {
  return new Promise((resolve) => {
    const url = `${BASE_URL}${path}`;
    const req = http.get(url, (res) => {
      const status = res.statusCode;
      const validStatuses = [200, 301, 302, 303, 307, 308];
      const isOk = validStatuses.includes(status);
      resolve({ path, status, ok: isOk });
    });

    req.on('error', (err) => {
      resolve({ path, error: err.message, ok: false });
    });

    req.end();
  });
}

main();
