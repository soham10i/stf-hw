import { useAuth } from "@/_core/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getLoginUrl } from "@/const";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Box,
  Cpu,
  Factory,
  Gauge,
  LayoutDashboard,
  Loader2,
  Zap,
} from "lucide-react";
import { Link } from "wouter";

export default function Home() {
  const { user, loading, isAuthenticated } = useAuth();

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-50">
        <div className="container flex h-16 items-center justify-between">
          <div className="flex items-center gap-3">
            <Factory className="h-8 w-8 text-primary" />
            <span className="text-xl font-bold">STF Digital Twin</span>
          </div>
          <nav className="flex items-center gap-4">
            {loading ? (
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            ) : isAuthenticated ? (
              <>
                <span className="text-sm text-muted-foreground">Welcome, {user?.name || "Operator"}</span>
                <Link href="/dashboard">
                  <Button>
                    <LayoutDashboard className="mr-2 h-4 w-4" />
                    Dashboard
                  </Button>
                </Link>
              </>
            ) : (
              <a href={getLoginUrl()}>
                <Button>Sign In</Button>
              </a>
            )}
          </nav>
        </div>
      </header>

      {/* Hero Section */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 grid-pattern opacity-30" />
        <div className="container relative py-24 md:py-32">
          <div className="mx-auto max-w-3xl text-center">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-4 py-2 text-sm text-primary">
              <Activity className="h-4 w-4" />
              Real-time Industrial Monitoring
            </div>
            <h1 className="mb-6 text-4xl font-bold tracking-tight md:text-6xl">
              Smart Tabletop Factory
              <span className="block text-primary">Digital Twin</span>
            </h1>
            <p className="mb-8 text-lg text-muted-foreground md:text-xl">
              A comprehensive warehouse automation system with real-time monitoring, hardware-in-the-loop simulation,
              and intelligent control capabilities for modern manufacturing.
            </p>
            <div className="flex flex-col gap-4 sm:flex-row sm:justify-center">
              {isAuthenticated ? (
                <Link href="/dashboard">
                  <Button size="lg" className="w-full sm:w-auto">
                    Open Dashboard
                    <ArrowRight className="ml-2 h-5 w-5" />
                  </Button>
                </Link>
              ) : (
                <a href={getLoginUrl()}>
                  <Button size="lg" className="w-full sm:w-auto">
                    Get Started
                    <ArrowRight className="ml-2 h-5 w-5" />
                  </Button>
                </a>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="border-t border-border bg-card/30 py-20">
        <div className="container">
          <div className="mb-12 text-center">
            <h2 className="mb-4 text-3xl font-bold">System Capabilities</h2>
            <p className="text-muted-foreground">
              Comprehensive tools for monitoring and controlling your smart factory
            </p>
          </div>
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            <FeatureCard
              icon={<Gauge className="h-8 w-8" />}
              title="Real-time Monitoring"
              description="Live visualization of robot positions, hardware states, and system telemetry with 1-second refresh intervals."
            />
            <FeatureCard
              icon={<Box className="h-8 w-8" />}
              title="Inventory Management"
              description="Track carriers, cookies, and inventory slots with color-coded status indicators and automated storage operations."
            />
            <FeatureCard
              icon={<Cpu className="h-8 w-8" />}
              title="Hardware Simulation"
              description="AsyncIO-based physics simulation at 10Hz for hardware-in-the-loop testing without physical equipment."
            />
            <FeatureCard
              icon={<AlertTriangle className="h-8 w-8" />}
              title="Safety Interlocks"
              description="Collision prevention system with automatic safety checks before executing movement commands."
            />
            <FeatureCard
              icon={<Zap className="h-8 w-8" />}
              title="Energy Monitoring"
              description="Track energy consumption across devices with historical analysis and predictive maintenance alerts."
            />
            <FeatureCard
              icon={<Activity className="h-8 w-8" />}
              title="Alert System"
              description="Automated notifications for hardware errors, inventory thresholds, and maintenance requirements."
            />
          </div>
        </div>
      </section>

      {/* Architecture Section */}
      <section className="border-t border-border py-20">
        <div className="container">
          <div className="mb-12 text-center">
            <h2 className="mb-4 text-3xl font-bold">System Architecture</h2>
            <p className="text-muted-foreground">Microservices-based design for scalability and reliability</p>
          </div>
          <div className="mx-auto max-w-4xl">
            <div className="grid gap-4 md:grid-cols-4">
              <ArchitectureBlock title="Database" subtitle="MySQL + Drizzle ORM" color="chart-1" />
              <ArchitectureBlock title="Backend" subtitle="tRPC + Express" color="chart-2" />
              <ArchitectureBlock title="Simulation" subtitle="Python AsyncIO" color="chart-3" />
              <ArchitectureBlock title="Dashboard" subtitle="React + Recharts" color="chart-5" />
            </div>
            <div className="mt-8 rounded-lg border border-border bg-card p-6">
              <h3 className="mb-4 font-semibold">Data Flow</h3>
              <div className="flex flex-wrap items-center justify-center gap-2 text-sm text-muted-foreground">
                <span className="rounded bg-secondary px-2 py-1">Mock Hardware</span>
                <ArrowRight className="h-4 w-4" />
                <span className="rounded bg-secondary px-2 py-1">MQTT Broker</span>
                <ArrowRight className="h-4 w-4" />
                <span className="rounded bg-secondary px-2 py-1">Controller</span>
                <ArrowRight className="h-4 w-4" />
                <span className="rounded bg-secondary px-2 py-1">Database</span>
                <ArrowRight className="h-4 w-4" />
                <span className="rounded bg-secondary px-2 py-1">Dashboard</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border bg-card/30 py-8">
        <div className="container text-center text-sm text-muted-foreground">
          <p>Smart Tabletop Factory Digital Twin - Industrial Automation Simulation Platform</p>
        </div>
      </footer>
    </div>
  );
}

function FeatureCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <Card className="border-border bg-card/50 transition-colors hover:bg-card">
      <CardHeader>
        <div className="mb-2 text-primary">{icon}</div>
        <CardTitle className="text-lg">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <CardDescription className="text-muted-foreground">{description}</CardDescription>
      </CardContent>
    </Card>
  );
}

function ArchitectureBlock({
  title,
  subtitle,
  color,
}: {
  title: string;
  subtitle: string;
  color: string;
}) {
  return (
    <div
      className={`rounded-lg border border-border bg-card p-4 text-center transition-transform hover:scale-105`}
      style={{ borderTopColor: `hsl(var(--${color}))`, borderTopWidth: "3px" }}
    >
      <div className="font-semibold">{title}</div>
      <div className="text-xs text-muted-foreground">{subtitle}</div>
    </div>
  );
}
