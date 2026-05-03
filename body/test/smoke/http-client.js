// HTTP client for smoke tests.
// Thin native-fetch wrapper around the body server's HTTP API.
// Uses AbortController to enforce timeoutMs.

/**
 * Creates an HTTP client bound to the body server.
 *
 * @param {object} opts
 * @param {string} [opts.host='127.0.0.1']
 * @param {number} [opts.port=3000]
 * @param {number} [opts.timeoutMs=30000]
 * @returns {{ status: Function, execute: Function, baseUrl: string }}
 */
function createClient({ host = '127.0.0.1', port = 3000, timeoutMs = 30000 } = {}) {
  const baseUrl = `http://${host}:${port}`;

  /**
   * Performs a fetch with AbortController timeout.
   * @param {string} url
   * @param {object} [init]
   * @returns {Promise<object>} Parsed JSON body
   */
  async function fetchWithTimeout(url, init = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const res = await fetch(url, { ...init, signal: controller.signal });

      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
      }

      return await res.json();
    } catch (err) {
      if (err.name === 'AbortError') {
        throw new Error(`Request to ${url} timed out after ${timeoutMs}ms`);
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * GET /status — returns parsed JSON; throws on non-2xx.
   */
  async function status() {
    return fetchWithTimeout(`${baseUrl}/status`);
  }

  /**
   * POST /execute with { tool, params }.
   * Returns the parsed envelope verbatim (does NOT throw on tool failure — caller inspects .success).
   *
   * @param {string} tool
   * @param {object} [params={}]
   * @returns {Promise<object>} The envelope: { success, data?, error?, tool, duration_ms }
   */
  async function execute(tool, params = {}) {
    return fetchWithTimeout(`${baseUrl}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool, params }),
    });
  }

  return { status, execute, baseUrl };
}

module.exports = { createClient };
