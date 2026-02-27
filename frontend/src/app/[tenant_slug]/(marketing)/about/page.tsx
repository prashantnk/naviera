// frontend/src/app/[tenant_slug]/(marketing)/about/page.tsx
import { getTenantBySlug } from "@/lib/api";

export default async function AboutPage({ params }: { params: Promise<{ tenant_slug: string }> }) {
    const { tenant_slug } = await params;
    const tenant = await getTenantBySlug(tenant_slug);

    return (
        <div className="bg-slate-50 min-h-screen py-16">
            <div className="container mx-auto px-4 md:px-6 max-w-4xl space-y-16 bg-white p-8 md:p-16 rounded-3xl shadow-sm border border-slate-100">

                <section className="space-y-6 text-slate-600 leading-relaxed text-lg">
                    <h1 className="text-4xl font-extrabold text-slate-900 text-center mb-8">About {tenant?.name || "Us"}</h1>
                    <p>
                        {tenant?.name} is one of India&rsquo;s fastest-growing logistics and supply chain companies, offering end-to-end solutions that meet the dynamic needs of modern businesses. Established with a vision to simplify logistics while ensuring speed, safety, and reliability, we have built a strong presence across India and international markets. Our extensive network of hubs, warehouses, and transport partners allows us to provide seamless connectivity between cities, states, and even countries. From express parcel delivery to specialized cargo movement, {tenant?.name} has become a trusted partner for enterprises, SMEs, and e-commerce players. Over the years, our continuous investment in technology, automation, and skilled manpower has helped us achieve operational excellence and customer satisfaction at every stage of delivery.
                    </p>
                    <p>
                        At {tenant?.name}, we go beyond traditional logistics by offering tailor-made services for industries such as pharmaceuticals, fashion, electronics, FMCG, automotive, and more. Our solutions are designed to handle high volumes with accuracy, covering air, train, and surface cargo, along with reverse logistics and warehousing facilities. We also specialize in temperature-controlled shipments, ensuring sensitive goods like medicines and perishable items are delivered safely and on time. By combining industry expertise with real-time tracking, transparent pricing, and customer-focused policies, we have created a logistics ecosystem that reduces delays, lowers costs, and enhances reliability. The company&rsquo;s ability to integrate multiple modes of transport with advanced digital tools makes it a one-stop solution for businesses aiming for efficiency and scalability.
                    </p>
                    <p>
                        What truly sets {tenant?.name} apart is our customer-first approach and commitment to innovation. We believe logistics is not just about moving goods&mdash;it is about creating value for clients and enabling their growth. This philosophy has helped us earn the trust of leading brands like Panasonic, LG, Apollo Tyres, Flipkart, Myntra, Reliance Retail, and many more who depend on us for their critical supply chain operations. With a highly trained workforce, state-of-the-art infrastructure, and a strong compliance framework, we deliver not just packages but confidence and reliability. Our focus on sustainability, safety, and long-term partnerships reflects our mission to build a smarter, greener, and more efficient logistics future.
                    </p>
                </section>

                <section className="space-y-6">
                    <h2 className="text-3xl font-bold text-slate-900 text-center mb-8">What We Offer</h2>
                    <ul className="space-y-6 text-lg text-slate-600">
                        <li><strong>Retail/Individuals:</strong> A dedicated online courier solution for personal parcel/shipments, with door step pickup and real-time tracking, services across India and overseas.</li>
                        <li><strong>B2C:</strong> End to end logistics solutions including express and premium delivery, cross-border cargo/shipping, warehousing solutions, and tech-enabled services to support growing brands.</li>
                        <li><strong>B2B:</strong> Reliable bulk shipping and cargo movement with advanced tech and a nationwide logistics network. We provide consultancy and analytics services for industrial projects and start-ups.</li>
                        <li><strong>E-commerce:</strong> Bulk shipment booking/manifesting within seconds and API integration of e-commerce shipping of your goods/shipments with real time basis tracking.</li>
                    </ul>
                </section>

            </div>
        </div>
    );
}