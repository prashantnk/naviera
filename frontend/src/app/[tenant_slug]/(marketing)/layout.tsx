// frontend/src/app/[tenant_slug]/(marketing)/layout.tsx
import { Footer } from "@/components/blocks/footer";
import { Header } from "@/components/blocks/header";
import { FloatingWhatsApp } from "@/components/blocks/floating-whatsapp";

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col relative">
      <Header />
      <div className="flex-1 bg-white">{children}</div>
      <Footer />
      <FloatingWhatsApp />
    </div>
  );
}
