import { useAuth } from "@/_core/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { trpc } from "@/lib/trpc";
import { getLoginUrl } from "@/const";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Box,
  CheckCircle2,
  Factory,
  Gauge,
  Loader2,
  Package,
  Play,
  Power,
  RefreshCw,
  Settings,
  Truck,
  XCircle,
  Zap,
} from "lucide-react";
import { Link } from "wouter";
import { useState, useEffect, useMemo } from "react";
import { toast } from "sonner";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  Legend,
  AreaChart,
  Area,
} from "recharts";
import { SLOT_COORDINATES, FLAVOR_COLORS, STATUS_COLORS, DASHBOARD_REFRESH_MS } from "../../../shared/stf-types";

export default function Dashboard() {
  const { user, loading: authLoading, isAuthenticated } = useAuth();
  const [selectedFlavor, setSelectedFlavor] = useState<"CHOCO" | "VANILLA" | "STRAWBERRY">("CHOCO");

  // Fetch dashboard data with auto-refresh
  const { data: dashboardData, isLoading, refetch } = trpc.dashboard.overview.useQuery(undefined, {
    refetchInterval: DASHBOARD_REFRESH_MS,
  });

  // Mutations
  const initializeMutation = trpc.maintenance.initialize.useMutation({
    onSuccess: () => {
      toast.success("System initialized successfully");
      refetch();
    },
    onError: (error) => toast.error(error.message),
  });

  const resetMutation = trpc.maintenance.reset.useMutation({
    onSuccess: () => {
      toast.success("System reset complete");
      refetch();
    },
    onError: (error) => toast.error(error.message),
  });

  const createOrderMutation = trpc.orders.create.useMutation({
    onSuccess: (data) => {
      toast.success(`Order created: ${data.batchUuid}`);
      refetch();
    },
    onError: (error) => toast.error(error.message),
  });

  const storeMutation = trpc.orders.store.useMutation({
    onSuccess: (data) => {
      toast.success(`Stored in slot ${data.slotName}`);
      refetch();
    },
    onError: (error) => toast.error(error.message),
  });

  const retrieveMutation = trpc.orders.retrieve.useMutation({
    onSuccess: () => {
      toast.success("Retrieve command sent");
      refetch();
    },
    onError: (error) => toast.error(error.message),
  });

  const moveToSlotMutation = trpc.hardware.moveToSlot.useMutation({
    onSuccess: (data) => {
      toast.success(`Moving to position (${data.targetPosition.x}, ${data.targetPosition.y})`);
      refetch();
    },
    onError: (error) => toast.error(error.message),
  });

  const acknowledgeAlertMutation = trpc.alerts.acknowledge.useMutation({
    onSuccess: () => {
      toast.success("Alert acknowledged");
      refetch();
    },
    onError: (error) => toast.error(error.message),
  });

  // Prepare robot position data for scatter plot - MUST be before early returns
  const robotPositions = useMemo(() => {
    if (!dashboardData?.hardware) return [];
    return dashboardData.hardware.map((hw) => ({
      x: hw.currentPositionX,
      y: hw.currentPositionY,
      name: hw.deviceId,
      status: hw.status,
    }));
  }, [dashboardData?.hardware]);

  // Prepare slot positions for the grid - MUST be before early returns
  const slotData = useMemo(() => {
    if (!dashboardData?.inventory) return [];
    return dashboardData.inventory.map((slot) => ({
      ...slot,
      coords: SLOT_COORDINATES[slot.slotName],
    }));
  }, [dashboardData?.inventory]);

  // Redirect if not authenticated
  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background">
        <Factory className="h-16 w-16 text-primary" />
        <h1 className="text-2xl font-bold">Authentication Required</h1>
        <p className="text-muted-foreground">Please sign in to access the dashboard</p>
        <a href={getLoginUrl()}>
          <Button>Sign In</Button>
        </a>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-50">
        <div className="container flex h-14 items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/">
              <Button variant="ghost" size="sm">
                <ArrowLeft className="mr-2 h-4 w-4" />
                Back
              </Button>
            </Link>
            <Separator orientation="vertical" className="h-6" />
            <div className="flex items-center gap-2">
              <Factory className="h-6 w-6 text-primary" />
              <span className="font-semibold">STF Digital Twin</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <div
                className={`h-2 w-2 rounded-full ${
                  dashboardData?.health?.healthy ? "bg-green-500" : "bg-red-500"
                } animate-pulse`}
              />
              <span className="text-sm text-muted-foreground">
                {dashboardData?.health?.healthy ? "System Healthy" : "System Alert"}
              </span>
            </div>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh
            </Button>
          </div>
        </div>
      </header>

      <main className="container py-6">
        {isLoading ? (
          <div className="flex h-96 items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : (
          <div className="space-y-6">
            {/* Stats Overview */}
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              <StatCard
                title="Inventory Slots"
                value={`${dashboardData?.stats?.inventory?.occupied || 0}/${dashboardData?.stats?.inventory?.total || 0}`}
                description="Occupied / Total"
                icon={<Box className="h-5 w-5" />}
                trend={dashboardData?.stats?.inventory?.empty === 0 ? "warning" : "normal"}
              />
              <StatCard
                title="Cookies Stored"
                value={dashboardData?.stats?.cookies?.stored || 0}
                description={`${dashboardData?.stats?.cookies?.baking || 0} baking, ${dashboardData?.stats?.cookies?.shipped || 0} shipped`}
                icon={<Package className="h-5 w-5" />}
              />
              <StatCard
                title="Active Alerts"
                value={dashboardData?.alerts?.length || 0}
                description="Unacknowledged"
                icon={<AlertTriangle className="h-5 w-5" />}
                trend={(dashboardData?.alerts?.length || 0) > 0 ? "error" : "success"}
              />
              <StatCard
                title="Hardware Status"
                value={dashboardData?.hardware?.filter((h) => h.status === "IDLE").length || 0}
                description={`of ${dashboardData?.hardware?.length || 0} devices idle`}
                icon={<Gauge className="h-5 w-5" />}
              />
            </div>

            {/* Main Content */}
            <div className="grid gap-6 lg:grid-cols-3">
              {/* Left Column - Visualization */}
              <div className="lg:col-span-2 space-y-6">
                {/* Robot Position Visualization */}
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2">
                      <Activity className="h-5 w-5 text-primary" />
                      Robot Position Monitor
                    </CardTitle>
                    <CardDescription>Real-time 2D visualization of HBW robot position</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="h-80 w-full grid-pattern rounded-lg border border-border p-4">
                      <ResponsiveContainer width="100%" height="100%">
                        <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                          <XAxis
                            type="number"
                            dataKey="x"
                            domain={[0, 400]}
                            name="X"
                            stroke="hsl(var(--muted-foreground))"
                            tick={{ fill: "hsl(var(--muted-foreground))" }}
                          />
                          <YAxis
                            type="number"
                            dataKey="y"
                            domain={[0, 400]}
                            name="Y"
                            stroke="hsl(var(--muted-foreground))"
                            tick={{ fill: "hsl(var(--muted-foreground))" }}
                          />
                          <Tooltip
                            content={({ active, payload }) => {
                              if (active && payload && payload.length) {
                                const data = payload[0].payload;
                                return (
                                  <div className="rounded-lg border border-border bg-card p-2 shadow-lg">
                                    <p className="font-semibold">{data.name}</p>
                                    <p className="text-sm text-muted-foreground">
                                      Position: ({data.x.toFixed(1)}, {data.y.toFixed(1)})
                                    </p>
                                    <p className="text-sm">
                                      Status:{" "}
                                      <span style={{ color: STATUS_COLORS[data.status] }}>{data.status}</span>
                                    </p>
                                  </div>
                                );
                              }
                              return null;
                            }}
                          />
                          {/* Slot markers */}
                          <Scatter
                            name="Slots"
                            data={Object.entries(SLOT_COORDINATES).map(([name, coords]) => ({
                              x: coords.x,
                              y: coords.y,
                              name,
                            }))}
                            fill="hsl(var(--muted-foreground))"
                            shape="square"
                            legendType="square"
                          />
                          {/* Robot positions */}
                          <Scatter
                            name="Robots"
                            data={robotPositions}
                            fill="hsl(var(--primary))"
                            shape="circle"
                          />
                        </ScatterChart>
                      </ResponsiveContainer>
                    </div>
                  </CardContent>
                </Card>

                {/* Inventory Grid */}
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2">
                      <Box className="h-5 w-5 text-primary" />
                      Inventory Grid
                    </CardTitle>
                    <CardDescription>3x3 warehouse slot status - click to retrieve</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-3 gap-4">
                      {["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"].map((slotName) => {
                        const slot = slotData.find((s) => s.slotName === slotName);
                        const isOccupied = slot?.carrierId !== null;
                        const cookie = slot?.cookie;
                        const flavorColor = cookie ? FLAVOR_COLORS[cookie.flavor] : undefined;

                        return (
                          <button
                            key={slotName}
                            onClick={() => {
                              if (isOccupied) {
                                retrieveMutation.mutate({ slotName });
                              } else {
                                moveToSlotMutation.mutate({ slotName });
                              }
                            }}
                            disabled={retrieveMutation.isPending || moveToSlotMutation.isPending}
                            className={`
                              relative aspect-square rounded-lg border-2 p-4 transition-all
                              ${isOccupied ? "border-primary bg-primary/10" : "border-border bg-card hover:border-primary/50"}
                              ${retrieveMutation.isPending || moveToSlotMutation.isPending ? "opacity-50" : ""}
                            `}
                          >
                            <div className="absolute inset-0 flex flex-col items-center justify-center">
                              <span className="text-lg font-bold">{slotName}</span>
                              {isOccupied && (
                                <>
                                  <div
                                    className="mt-2 h-6 w-6 rounded-full"
                                    style={{ backgroundColor: flavorColor || "hsl(var(--muted))" }}
                                  />
                                  <span className="mt-1 text-xs text-muted-foreground">
                                    {cookie?.flavor || "Unknown"}
                                  </span>
                                </>
                              )}
                              {!isOccupied && (
                                <span className="mt-2 text-xs text-muted-foreground">Empty</span>
                              )}
                            </div>
                            {isOccupied && (
                              <div className="absolute right-2 top-2">
                                <Package className="h-4 w-4 text-primary" />
                              </div>
                            )}
                          </button>
                        );
                      })}
                    </div>
                    <div className="mt-4 flex items-center justify-center gap-6 text-sm">
                      <div className="flex items-center gap-2">
                        <div className="h-4 w-4 rounded" style={{ backgroundColor: FLAVOR_COLORS.CHOCO }} />
                        <span>Choco</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="h-4 w-4 rounded" style={{ backgroundColor: FLAVOR_COLORS.VANILLA }} />
                        <span>Vanilla</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="h-4 w-4 rounded" style={{ backgroundColor: FLAVOR_COLORS.STRAWBERRY }} />
                        <span>Strawberry</span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>

              {/* Right Column - Controls & Alerts */}
              <div className="space-y-6">
                {/* Control Panel */}
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2">
                      <Settings className="h-5 w-5 text-primary" />
                      Control Panel
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {/* Create Order */}
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Create New Order</label>
                      <div className="flex gap-2">
                        <Select
                          value={selectedFlavor}
                          onValueChange={(v) => setSelectedFlavor(v as typeof selectedFlavor)}
                        >
                          <SelectTrigger className="flex-1">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="CHOCO">Chocolate</SelectItem>
                            <SelectItem value="VANILLA">Vanilla</SelectItem>
                            <SelectItem value="STRAWBERRY">Strawberry</SelectItem>
                          </SelectContent>
                        </Select>
                        <Button
                          onClick={() => createOrderMutation.mutate({ flavor: selectedFlavor })}
                          disabled={createOrderMutation.isPending}
                        >
                          {createOrderMutation.isPending ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Play className="h-4 w-4" />
                          )}
                        </Button>
                      </div>
                    </div>

                    <Separator />

                    {/* Store Random Cookie */}
                    <Button
                      className="w-full"
                      variant="outline"
                      onClick={async () => {
                        // First create an order, then store it
                        const flavors: Array<"CHOCO" | "VANILLA" | "STRAWBERRY"> = ["CHOCO", "VANILLA", "STRAWBERRY"];
                        const randomFlavor = flavors[Math.floor(Math.random() * flavors.length)];
                        try {
                          const order = await createOrderMutation.mutateAsync({ flavor: randomFlavor });
                          await storeMutation.mutateAsync({ batchUuid: order.batchUuid });
                        } catch (e) {
                          // Error already handled by mutation
                        }
                      }}
                      disabled={createOrderMutation.isPending || storeMutation.isPending}
                    >
                      <Truck className="mr-2 h-4 w-4" />
                      Store Random Cookie
                    </Button>

                    <Separator />

                    {/* System Controls */}
                    <div className="space-y-2">
                      <label className="text-sm font-medium">System Controls</label>
                      <div className="grid grid-cols-2 gap-2">
                        <Button
                          variant="outline"
                          onClick={() => initializeMutation.mutate()}
                          disabled={initializeMutation.isPending}
                        >
                          {initializeMutation.isPending ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : (
                            <Power className="mr-2 h-4 w-4" />
                          )}
                          Initialize
                        </Button>
                        <Button
                          variant="destructive"
                          onClick={() => resetMutation.mutate()}
                          disabled={resetMutation.isPending}
                        >
                          {resetMutation.isPending ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : (
                            <RefreshCw className="mr-2 h-4 w-4" />
                          )}
                          Reset
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {/* Hardware Status */}
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2">
                      <Gauge className="h-5 w-5 text-primary" />
                      Hardware Status
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      {dashboardData?.hardware?.map((device) => (
                        <div
                          key={device.deviceId}
                          className="flex items-center justify-between rounded-lg border border-border bg-secondary/30 p-3"
                        >
                          <div className="flex items-center gap-3">
                            <div
                              className="h-3 w-3 rounded-full"
                              style={{ backgroundColor: STATUS_COLORS[device.status] }}
                            />
                            <div>
                              <div className="font-medium">{device.deviceId}</div>
                              <div className="text-xs text-muted-foreground mono">
                                ({device.currentPositionX.toFixed(0)}, {device.currentPositionY.toFixed(0)})
                              </div>
                            </div>
                          </div>
                          <Badge
                            variant={device.status === "IDLE" ? "default" : device.status === "ERROR" ? "destructive" : "secondary"}
                          >
                            {device.status}
                          </Badge>
                        </div>
                      ))}
                      {(!dashboardData?.hardware || dashboardData.hardware.length === 0) && (
                        <div className="text-center text-sm text-muted-foreground py-4">
                          No hardware devices registered. Click Initialize to set up.
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>

                {/* Alerts */}
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2">
                      <AlertTriangle className="h-5 w-5 text-primary" />
                      Active Alerts
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ScrollArea className="h-48">
                      <div className="space-y-2">
                        {dashboardData?.alerts?.map((alert) => (
                          <div
                            key={alert.id}
                            className={`
                              rounded-lg border p-3 transition-colors
                              ${alert.severity === "CRITICAL" ? "border-red-500/50 bg-red-500/10" : ""}
                              ${alert.severity === "WARNING" ? "border-yellow-500/50 bg-yellow-500/10" : ""}
                              ${alert.severity === "INFO" ? "border-blue-500/50 bg-blue-500/10" : ""}
                            `}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="flex-1">
                                <div className="flex items-center gap-2">
                                  <Badge
                                    variant={
                                      alert.severity === "CRITICAL"
                                        ? "destructive"
                                        : alert.severity === "WARNING"
                                        ? "default"
                                        : "secondary"
                                    }
                                  >
                                    {alert.severity}
                                  </Badge>
                                  <span className="text-xs text-muted-foreground">
                                    {new Date(alert.timestamp).toLocaleTimeString()}
                                  </span>
                                </div>
                                <p className="mt-1 text-sm">{alert.message}</p>
                              </div>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => acknowledgeAlertMutation.mutate({ alertId: Number(alert.id) })}
                                disabled={acknowledgeAlertMutation.isPending}
                              >
                                <CheckCircle2 className="h-4 w-4" />
                              </Button>
                            </div>
                          </div>
                        ))}
                        {(!dashboardData?.alerts || dashboardData.alerts.length === 0) && (
                          <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                            <CheckCircle2 className="mb-2 h-8 w-8 text-green-500" />
                            <span className="text-sm">No active alerts</span>
                          </div>
                        )}
                      </div>
                    </ScrollArea>
                  </CardContent>
                </Card>

                {/* Recent Commands */}
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2">
                      <Zap className="h-5 w-5 text-primary" />
                      Recent Commands
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ScrollArea className="h-32">
                      <div className="space-y-2">
                        {dashboardData?.recentCommands?.slice(0, 5).map((cmd) => (
                          <div
                            key={cmd.id}
                            className="flex items-center justify-between rounded border border-border bg-secondary/20 px-3 py-2 text-sm"
                          >
                            <div className="flex items-center gap-2">
                              {cmd.status === "COMPLETED" && <CheckCircle2 className="h-4 w-4 text-green-500" />}
                              {cmd.status === "FAILED" && <XCircle className="h-4 w-4 text-red-500" />}
                              {cmd.status === "EXECUTING" && <Loader2 className="h-4 w-4 animate-spin text-blue-500" />}
                              {cmd.status === "PENDING" && <Activity className="h-4 w-4 text-yellow-500" />}
                              <span className="mono">{cmd.commandType}</span>
                            </div>
                            <span className="text-xs text-muted-foreground">
                              {new Date(cmd.timestamp).toLocaleTimeString()}
                            </span>
                          </div>
                        ))}
                        {(!dashboardData?.recentCommands || dashboardData.recentCommands.length === 0) && (
                          <div className="text-center text-sm text-muted-foreground py-4">
                            No commands yet
                          </div>
                        )}
                      </div>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function StatCard({
  title,
  value,
  description,
  icon,
  trend,
}: {
  title: string;
  value: string | number;
  description: string;
  icon: React.ReactNode;
  trend?: "normal" | "success" | "warning" | "error";
}) {
  const trendColors = {
    normal: "text-primary",
    success: "text-green-500",
    warning: "text-yellow-500",
    error: "text-red-500",
  };

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{title}</p>
            <p className={`text-2xl font-bold ${trendColors[trend || "normal"]}`}>{value}</p>
            <p className="text-xs text-muted-foreground">{description}</p>
          </div>
          <div className={`rounded-lg bg-primary/10 p-3 ${trendColors[trend || "normal"]}`}>{icon}</div>
        </div>
      </CardContent>
    </Card>
  );
}
