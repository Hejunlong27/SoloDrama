export type ProviderDiagnosticStatus = "healthy" | "degraded" | "unhealthy" | "unknown";
export type ProviderDiagnosticCheckStatus = "passed" | "failed" | "skipped" | "warning";

export type ProviderDiagnosticCheck = {
  name: string;
  status: ProviderDiagnosticCheckStatus;
  latency?: number;
  errorCode?: string;
  message?: string;
};

export type ProviderDiagnosticResult = {
  providerId: string;
  providerType: string;
  status: ProviderDiagnosticStatus;
  checks: ProviderDiagnosticCheck[];
  latency?: number;
  checkedAt: number;
  capabilities?: string[];
};

export interface ProviderDiagnostics {
  diagnose(signal?: AbortSignal): Promise<ProviderDiagnosticResult>;
}