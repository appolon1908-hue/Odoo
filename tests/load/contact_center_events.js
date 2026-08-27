import http from "k6/http";
import { check } from "k6";
import { Counter } from "k6/metrics";

const endpoint = __ENV.CC_EVENT_ENDPOINT || "";
const token = __ENV.CC_SERVICE_TOKEN || "";
const forbiddenHosts = new Set([
  "api.codestra.co",
  "auth.codestra.co",
  "codestra.co",
  "65.109.65.169",
  "65.21.67.207",
  "37.27.128.39",
]);

if (!endpoint || !token) {
  throw new Error("CC_EVENT_ENDPOINT and CC_SERVICE_TOKEN are required.");
}
const target = new URL(endpoint);
if (forbiddenHosts.has(target.hostname)) {
  throw new Error(`Production or infrastructure target is forbidden: ${target.hostname}`);
}
if (!target.pathname.endsWith("/v1/contact-center/events/vicidial")) {
  throw new Error("Only the canonical isolated VICIdial event endpoint is permitted.");
}
const isolated =
  target.hostname === "localhost" ||
  target.hostname === "127.0.0.1" ||
  target.hostname.startsWith("staging.") ||
  target.hostname.includes("isolated-staging") ||
  target.hostname.endsWith(".test");
if (!isolated) {
  throw new Error(`Target is not an approved isolated environment: ${target.hostname}`);
}

export const options = {
  scenarios: {
    event_ingestion: {
      executor: "constant-arrival-rate",
      rate: 50,
      timeUnit: "1s",
      duration: "5m",
      preAllocatedVUs: 50,
      maxVUs: 150,
    },
  },
  thresholds: {
    http_req_failed: ["rate==0"],
    http_req_duration: ["p(95)<2000"],
    duplicate_side_effects: ["count==0"],
  },
};

const duplicateSideEffects = new Counter("duplicate_side_effects");

export default function () {
  const sequence = `${__VU}-${__ITER}-${Date.now()}`;
  const eventId = `cert-${sequence}`;
  const body = JSON.stringify({
    event_id: eventId,
    event_type: "call.ended",
    schema_version: 1,
    occurred_at: new Date().toISOString(),
    source: "vicidial-certification",
    tenant_id: "company-fixture",
    campaign_id: "campaign-fixture",
    correlation_id: `interaction-${sequence}`,
    subject: { type: "call_leg", id: `call-${sequence}` },
    data: { synthetic: true, telephone: "+15555550100" },
  });
  const params = {
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "X-Request-ID": `request-${sequence}`,
      "X-Correlation-ID": `interaction-${sequence}`,
      "X-Event-Schema-Version": "1",
      "Idempotency-Key": eventId,
    },
  };
  const response = http.post(endpoint, body, params);
  const passed = check(response, {
    "event accepted or exact replayed": (result) => [200, 201, 202].includes(result.status),
    "no server error": (result) => result.status < 500,
  });
  if (!passed && response.status === 409 && response.body.includes("duplicate_side_effect")) {
    duplicateSideEffects.add(1);
  }
}
