// frontend/src/components/blocks/showcase-svgs.ts
/**
 * Self-contained inline SVG data URIs for the 4 homepage showcase slides.
 *
 * Embedding the 4 curated logistics illustrations as `data:image/svg+xml;utf8,...`
 * data URIs guarantees:
 * 1. Zero HTTP network requests on initial homepage load or during 4.5s slide rotation.
 * 2. Instant synchronous decoding (`complete === true`, `naturalWidth === 960`,
 *    `naturalHeight === 600` in 0ms) with zero layout shift or flash.
 */

export function toSvgDataUri(svgMarkup: string): string {
  return `data:image/svg+xml;utf8,${encodeURIComponent(svgMarkup.trim())}`;
}

const B2C_EXPRESS_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600" viewBox="0 0 960 600" fill="none">
  <defs>
    <linearGradient id="bg1" x1="0" y1="0" x2="960" y2="600" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#0F172A" />
      <stop offset="55%" stop-color="#1E293B" />
      <stop offset="100%" stop-color="#0F172A" />
    </linearGradient>
    <linearGradient id="accent1" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#DC2626" />
      <stop offset="100%" stop-color="#EA580C" />
    </linearGradient>
    <linearGradient id="cardGlass1" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#1E293B" stop-opacity="0.95" />
      <stop offset="100%" stop-color="#0F172A" stop-opacity="0.95" />
    </linearGradient>
    <pattern id="grid1" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#334155" stroke-width="0.7" stroke-opacity="0.45" />
    </pattern>
  </defs>
  <rect width="960" height="600" fill="url(#bg1)" />
  <rect width="960" height="600" fill="url(#grid1)" />
  <circle cx="780" cy="120" r="210" fill="#DC2626" fill-opacity="0.12" />
  <circle cx="180" cy="480" r="220" fill="#38BDF8" fill-opacity="0.1" />
  <rect x="48" y="38" width="864" height="54" rx="14" fill="#1E293B" stroke="#334155" stroke-width="1.5" />
  <circle cx="76" cy="65" r="6" fill="#22C55E" />
  <text x="92" y="70" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" letter-spacing="1">B2C EXPRESS PARCEL NETWORK · LIVE DISPATCH TELEMETRY</text>
  <rect x="708" y="50" width="186" height="30" rx="8" fill="#0F172A" stroke="#475569" />
  <text x="801" y="70" text-anchor="middle" fill="#38BDF8" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">29,000+ PIN CODES</text>
  <rect x="48" y="114" width="520" height="444" rx="20" fill="url(#cardGlass1)" stroke="#334155" stroke-width="1.5" />
  <rect x="76" y="142" width="128" height="28" rx="6" fill="url(#accent1)" />
  <text x="140" y="160" text-anchor="middle" fill="#FFFFFF" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" letter-spacing="0.8">EXPRESS AIR / SURF</text>
  <text x="218" y="161" fill="#94A3B8" font-family="monospace" font-size="14" font-weight="700">AWB #LGSM84920143</text>
  <rect x="432" y="140" width="108" height="30" rx="15" fill="#14532D" stroke="#22C55E" stroke-width="1.2" />
  <text x="486" y="159" text-anchor="middle" fill="#4ADE80" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">OUT FOR DELIVERY</text>
  <rect x="76" y="190" width="464" height="106" rx="14" fill="#0F172A" stroke="#334155" />
  <text x="102" y="218" fill="#64748B" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" letter-spacing="1">ORIGIN HUB</text>
  <text x="102" y="246" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="800">New Delhi</text>
  <text x="102" y="270" fill="#94A3B8" font-family="monospace" font-size="13">PIN 110037 · Okhla Hub</text>
  <line x1="252" y1="242" x2="352" y2="242" stroke="#DC2626" stroke-width="3" stroke-dasharray="6 5" />
  <circle cx="252" cy="242" r="5" fill="#DC2626" />
  <polygon points="358,242 346,235 346,249" fill="#DC2626" />
  <rect x="270" y="212" width="68" height="20" rx="10" fill="#1E293B" stroke="#475569" />
  <text x="304" y="226" text-anchor="middle" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">NEXT-DAY</text>
  <text x="514" y="218" text-anchor="end" fill="#64748B" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" letter-spacing="1">DESTINATION</text>
  <text x="514" y="246" text-anchor="end" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="800">Mumbai</text>
  <text x="514" y="270" text-anchor="end" fill="#94A3B8" font-family="monospace" font-size="13">PIN 400001 · Fort</text>
  <text x="76" y="330" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700" letter-spacing="0.8">REAL-TIME SHIPMENT LIFECYCLE</text>
  <line x1="100" y1="364" x2="510" y2="364" stroke="#334155" stroke-width="4" />
  <line x1="100" y1="364" x2="395" y2="364" stroke="#22C55E" stroke-width="4" />
  <circle cx="100" cy="364" r="11" fill="#22C55E" />
  <path d="M95 364 L99 368 L106 360" stroke="#0F172A" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
  <text x="100" y="394" text-anchor="middle" fill="#E2E8F0" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">Picked Up</text>
  <circle cx="240" cy="364" r="11" fill="#22C55E" />
  <path d="M235 364 L239 368 L246 360" stroke="#0F172A" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
  <text x="240" y="394" text-anchor="middle" fill="#E2E8F0" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">Bagged at Hub</text>
  <circle cx="385" cy="364" r="11" fill="#22C55E" />
  <circle cx="385" cy="364" r="5" fill="#0F172A" />
  <text x="385" y="394" text-anchor="middle" fill="#4ADE80" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">Out for Delivery</text>
  <circle cx="510" cy="364" r="11" fill="#1E293B" stroke="#64748B" stroke-width="2.5" />
  <text x="510" y="394" text-anchor="middle" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="600">OTP Delivered</text>
  <rect x="76" y="424" width="464" height="106" rx="14" fill="#0F172A" stroke="#334155" />
  <g fill="#E2E8F0">
    <rect x="98" y="444" width="4" height="48" />
    <rect x="106" y="444" width="2" height="48" />
    <rect x="112" y="444" width="6" height="48" />
    <rect x="122" y="444" width="2" height="48" />
    <rect x="128" y="444" width="4" height="48" />
    <rect x="136" y="444" width="8" height="48" />
    <rect x="148" y="444" width="2" height="48" />
    <rect x="154" y="444" width="4" height="48" />
    <rect x="162" y="444" width="6" height="48" />
    <rect x="172" y="444" width="2" height="48" />
    <rect x="178" y="444" width="4" height="48" />
    <rect x="186" y="444" width="6" height="48" />
    <rect x="196" y="444" width="2" height="48" />
    <rect x="202" y="444" width="8" height="48" />
    <rect x="214" y="444" width="4" height="48" />
    <rect x="222" y="444" width="2" height="48" />
    <rect x="228" y="444" width="6" height="48" />
  </g>
  <text x="166" y="510" text-anchor="middle" fill="#94A3B8" font-family="monospace" font-size="11">LGSM-8492-0143</text>
  <line x1="258" y1="440" x2="258" y2="514" stroke="#334155" stroke-width="1.5" />
  <text x="280" y="462" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="15" font-weight="700">Thermal 4×6&quot; Label &amp; Manifest Ready</text>
  <text x="280" y="486" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="13">Weight Slab: 0.5 kg – 5.0 kg · Prepaid &amp; COD</text>
  <text x="280" y="508" fill="#38BDF8" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">SMS / WhatsApp Consignee Tracking Link Active</text>
  <rect x="592" y="114" width="320" height="226" rx="20" fill="url(#cardGlass1)" stroke="#334155" stroke-width="1.5" />
  <text x="620" y="148" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" letter-spacing="1">DOORSTEP PICKUP &amp; SCAN</text>
  <g transform="translate(685, 165)">
    <polygon points="65,0 130,32 65,64 0,32" fill="#F59E0B" />
    <polygon points="56,4 74,4 74,60 56,60" fill="#FEF3C7" fill-opacity="0.75" />
    <polygon points="0,32 65,64 65,134 0,102" fill="#D97706" />
    <polygon points="65,64 130,32 130,102 65,134" fill="#B45309" />
    <polygon points="14,52 50,70 50,104 14,86" fill="#FFFFFF" />
    <line x1="20" y1="64" x2="44" y2="76" stroke="#0F172A" stroke-width="3" />
    <line x1="20" y1="74" x2="40" y2="84" stroke="#DC2626" stroke-width="2.5" />
  </g>
  <text x="752" y="322" text-anchor="middle" fill="#E2E8F0" font-family="system-ui, -apple-system, sans-serif" font-size="13" font-weight="700">Tamper-Evident Flyer &amp; Box</text>
  <rect x="592" y="358" width="320" height="200" rx="20" fill="url(#cardGlass1)" stroke="#334155" stroke-width="1.5" />
  <text x="620" y="392" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" letter-spacing="1">CONSIGNEE OTP VERIFICATION</text>
  <rect x="620" y="410" width="264" height="58" rx="12" fill="#0F172A" stroke="#22C55E" stroke-width="1.5" />
  <text x="640" y="446" fill="#4ADE80" font-family="monospace" font-size="24" font-weight="800" letter-spacing="6">4 8 2 9</text>
  <rect x="780" y="424" width="88" height="30" rx="8" fill="#14532D" />
  <text x="824" y="444" text-anchor="middle" fill="#86EFAC" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">VERIFIED</text>
  <text x="620" y="500" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="15" font-weight="700">99.8% First-Attempt Delivery SLA</text>
  <text x="620" y="524" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="13">Instant POD capture &amp; NDR buyer confirmation</text>
</svg>`;

const B2B_CARGO_FLEET_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600" viewBox="0 0 960 600" fill="none">
  <defs>
    <linearGradient id="bg2" x1="0" y1="0" x2="960" y2="600" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#0F172A" />
      <stop offset="55%" stop-color="#172554" />
      <stop offset="100%" stop-color="#0F172A" />
    </linearGradient>
    <linearGradient id="accent2" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0284C7" />
      <stop offset="100%" stop-color="#2563EB" />
    </linearGradient>
    <pattern id="grid2" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#334155" stroke-width="0.7" stroke-opacity="0.45" />
    </pattern>
  </defs>
  <rect width="960" height="600" fill="url(#bg2)" />
  <rect width="960" height="600" fill="url(#grid2)" />
  <circle cx="800" cy="480" r="220" fill="#0284C7" fill-opacity="0.14" />
  <circle cx="150" cy="140" r="190" fill="#F59E0B" fill-opacity="0.1" />
  <rect x="48" y="38" width="864" height="54" rx="14" fill="#1E293B" stroke="#334155" stroke-width="1.5" />
  <circle cx="76" cy="65" r="6" fill="#38BDF8" />
  <text x="92" y="70" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" letter-spacing="1">B2B HEAVY CARGO · PTL &amp; FTL LORRY RECEIPT (LR) NETWORK</text>
  <rect x="698" y="50" width="196" height="30" rx="8" fill="#0F172A" stroke="#475569" />
  <text x="796" y="70" text-anchor="middle" fill="#FBBF24" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">E-WAY BILL VERIFIED</text>
  <rect x="48" y="114" width="530" height="444" rx="20" fill="#1E293B" fill-opacity="0.95" stroke="#334155" stroke-width="1.5" />
  <rect x="76" y="142" width="136" height="28" rx="6" fill="url(#accent2)" />
  <text x="144" y="160" text-anchor="middle" fill="#FFFFFF" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" letter-spacing="0.8">PTL / FTL CARGO</text>
  <text x="226" y="161" fill="#E2E8F0" font-family="monospace" font-size="14" font-weight="700">LR #8004921074</text>
  <rect x="412" y="140" width="138" height="30" rx="15" fill="#0C4A6E" stroke="#38BDF8" stroke-width="1.2" />
  <text x="481" y="159" text-anchor="middle" fill="#7DD3FC" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">LINEHAUL IN TRANSIT</text>
  <rect x="76" y="188" width="474" height="162" rx="14" fill="#0F172A" stroke="#334155" />
  <line x1="96" y1="322" x2="530" y2="322" stroke="#475569" stroke-width="3" stroke-dasharray="14 10" />
  <rect x="130" y="216" width="230" height="82" rx="8" fill="#1E293B" stroke="#38BDF8" stroke-width="2" />
  <rect x="144" y="232" width="44" height="54" rx="4" fill="#F59E0B" fill-opacity="0.85" />
  <rect x="196" y="232" width="44" height="54" rx="4" fill="#D97706" fill-opacity="0.85" />
  <rect x="248" y="232" width="44" height="54" rx="4" fill="#F59E0B" fill-opacity="0.85" />
  <rect x="300" y="232" width="44" height="54" rx="4" fill="#D97706" fill-opacity="0.85" />
  <path d="M364 236 L416 236 L434 264 L434 298 L364 298 Z" fill="#DC2626" />
  <polygon points="392,244 414,244 426,264 392,264" fill="#BAE6FD" />
  <circle cx="176" cy="304" r="14" fill="#0F172A" stroke="#94A3B8" stroke-width="4" />
  <circle cx="216" cy="304" r="14" fill="#0F172A" stroke="#94A3B8" stroke-width="4" />
  <circle cx="324" cy="304" r="14" fill="#0F172A" stroke="#94A3B8" stroke-width="4" />
  <circle cx="404" cy="304" r="14" fill="#0F172A" stroke="#94A3B8" stroke-width="4" />
  <text x="454" y="246" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="13" font-weight="800">32-FT CONTAINER</text>
  <text x="454" y="266" fill="#38BDF8" font-family="monospace" font-size="11">GPS LOCKED</text>
  <rect x="76" y="368" width="148" height="78" rx="12" fill="#0F172A" stroke="#334155" />
  <text x="94" y="394" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">MASTER CARTONS</text>
  <text x="94" y="428" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="24" font-weight="800">24 Boxes</text>
  <rect x="239" y="368" width="148" height="78" rx="12" fill="#0F172A" stroke="#334155" />
  <text x="257" y="394" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">CHARGEABLE WT</text>
  <text x="257" y="428" fill="#38BDF8" font-family="system-ui, -apple-system, sans-serif" font-size="24" font-weight="800">1,480 kg</text>
  <rect x="402" y="368" width="148" height="78" rx="12" fill="#0F172A" stroke="#334155" />
  <text x="420" y="394" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">TRANSIT RISK</text>
  <text x="420" y="428" fill="#4ADE80" font-family="system-ui, -apple-system, sans-serif" font-size="20" font-weight="800">ROV / FOV</text>
  <rect x="76" y="464" width="474" height="68" rx="12" fill="#0F172A" stroke="#334155" />
  <text x="98" y="492" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">E-Way Bill #1419 8823 0912 · Consignor Invoice Linked</text>
  <text x="98" y="514" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="12">Gurgaon Bilaspur Hub (122413) → Bhiwandi Mega Gateway (421302)</text>
  <rect x="602" y="114" width="310" height="212" rx="20" fill="#1E293B" fill-opacity="0.95" stroke="#334155" stroke-width="1.5" />
  <text x="628" y="148" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" letter-spacing="1">FLEET PICKUP MANIFEST (PUR)</text>
  <rect x="628" y="166" width="258" height="66" rx="12" fill="#0F172A" stroke="#334155" />
  <text x="646" y="194" fill="#F8FAFC" font-family="monospace" font-size="15" font-weight="700">PUR #PUR-2026-0419</text>
  <text x="646" y="216" fill="#4ADE80" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">Dock Bay 04 · 14:00–18:00 Slot</text>
  <text x="628" y="264" fill="#E2E8F0" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">Standard &amp; Blind Dock Pickups</text>
  <text x="628" y="288" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="12">Multi-LR consolidation &amp; thermal box labels</text>
  <rect x="602" y="346" width="310" height="212" rx="20" fill="#1E293B" fill-opacity="0.95" stroke="#334155" stroke-width="1.5" />
  <text x="628" y="380" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" letter-spacing="1">APPOINTMENT &amp; CSD DELIVERY</text>
  <rect x="628" y="398" width="258" height="66" rx="12" fill="#0F172A" stroke="#38BDF8" stroke-width="1.2" />
  <text x="646" y="426" fill="#38BDF8" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">Mall / Warehouse Slot Confirmed</text>
  <text x="646" y="448" fill="#E2E8F0" font-family="system-ui, -apple-system, sans-serif" font-size="12">POD Stamp &amp; Digital Signature</text>
  <text x="628" y="496" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">Pan-India Industrial Coverage</text>
  <text x="628" y="520" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="12">Factory-to-Distributor &amp; FTL Charter</text>
</svg>`;

const HUB_SORTATION_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600" viewBox="0 0 960 600" fill="none">
  <defs>
    <linearGradient id="bg3" x1="0" y1="0" x2="960" y2="600" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#0F172A" />
      <stop offset="55%" stop-color="#1E293B" />
      <stop offset="100%" stop-color="#0F172A" />
    </linearGradient>
    <pattern id="grid3" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#334155" stroke-width="0.7" stroke-opacity="0.45" />
    </pattern>
  </defs>
  <rect width="960" height="600" fill="url(#bg3)" />
  <rect width="960" height="600" fill="url(#grid3)" />
  <circle cx="780" cy="140" r="220" fill="#22C55E" fill-opacity="0.1" />
  <circle cx="180" cy="460" r="210" fill="#A855F7" fill-opacity="0.1" />
  <rect x="48" y="38" width="864" height="54" rx="14" fill="#1E293B" stroke="#334155" stroke-width="1.5" />
  <circle cx="76" cy="65" r="6" fill="#A855F7" />
  <text x="92" y="70" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" letter-spacing="1">AUTOMATED HUB SORTATION · LASER VOLUMETRIC &amp; NDR CONTROL TOWER</text>
  <rect x="698" y="50" width="196" height="30" rx="8" fill="#0F172A" stroke="#475569" />
  <text x="796" y="70" text-anchor="middle" fill="#4ADE80" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">100% WEIGHT AUDIT</text>
  <rect x="48" y="114" width="530" height="444" rx="20" fill="#1E293B" fill-opacity="0.95" stroke="#334155" stroke-width="1.5" />
  <rect x="76" y="142" width="164" height="28" rx="6" fill="#7C3AED" />
  <text x="158" y="160" text-anchor="middle" fill="#FFFFFF" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" letter-spacing="0.8">FALCON DIM-SCANNER</text>
  <text x="254" y="161" fill="#E2E8F0" font-family="monospace" font-size="13" font-weight="700">GATE #HUB-DEL-09</text>
  <rect x="424" y="140" width="126" height="30" rx="15" fill="#14532D" stroke="#22C55E" stroke-width="1.2" />
  <text x="487" y="159" text-anchor="middle" fill="#4ADE80" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">PHOTO VERIFIED</text>
  <rect x="76" y="188" width="474" height="178" rx="14" fill="#0F172A" stroke="#334155" />
  <path d="M160 340 L160 206 L460 206 L460 340" stroke="#38BDF8" stroke-width="3" fill="none" />
  <line x1="310" y1="206" x2="220" y2="310" stroke="#22C55E" stroke-width="1.5" stroke-dasharray="4 4" />
  <line x1="310" y1="206" x2="310" y2="310" stroke="#22C55E" stroke-width="1.5" stroke-dasharray="4 4" />
  <line x1="310" y1="206" x2="400" y2="310" stroke="#22C55E" stroke-width="1.5" stroke-dasharray="4 4" />
  <rect x="246" y="246" width="128" height="76" rx="6" fill="#F59E0B" fill-opacity="0.25" stroke="#FBBF24" stroke-width="2" />
  <text x="310" y="282" text-anchor="middle" fill="#FEF3C7" font-family="monospace" font-size="13" font-weight="700">62 × 45 × 38 cm</text>
  <text x="310" y="304" text-anchor="middle" fill="#4ADE80" font-family="monospace" font-size="12" font-weight="700">VOL: 21.20 kg</text>
  <line x1="110" y1="340" x2="510" y2="340" stroke="#64748B" stroke-width="4" />
  <circle cx="140" cy="348" r="5" fill="#94A3B8" />
  <circle cx="200" cy="348" r="5" fill="#94A3B8" />
  <circle cx="260" cy="348" r="5" fill="#94A3B8" />
  <circle cx="320" cy="348" r="5" fill="#94A3B8" />
  <circle cx="380" cy="348" r="5" fill="#94A3B8" />
  <circle cx="440" cy="348" r="5" fill="#94A3B8" />
  <circle cx="490" cy="348" r="5" fill="#94A3B8" />
  <rect x="76" y="384" width="228" height="72" rx="12" fill="#0F172A" stroke="#334155" />
  <text x="96" y="410" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">DECLARED VS. HUB BILLED</text>
  <text x="96" y="438" fill="#F8FAFC" font-family="monospace" font-size="17" font-weight="800">14.5 kg → 21.2 kg</text>
  <rect x="322" y="384" width="228" height="72" rx="12" fill="#0F172A" stroke="#334155" />
  <text x="342" y="410" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">DISPUTE PROTECTION</text>
  <text x="342" y="438" fill="#4ADE80" font-family="system-ui, -apple-system, sans-serif" font-size="16" font-weight="800">Sorter Image Attached</text>
  <rect x="76" y="472" width="474" height="62" rx="12" fill="#0F172A" stroke="#334155" />
  <text x="96" y="500" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">Atomic Repricing &amp; GST Note Adjustment</text>
  <text x="96" y="520" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="12">7-day merchant dispute window with 1-click credit refund on approval</text>
  <rect x="602" y="114" width="310" height="444" rx="20" fill="#1E293B" fill-opacity="0.95" stroke="#334155" stroke-width="1.5" />
  <text x="628" y="148" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" letter-spacing="1">NDR &amp; EXCEPTION CONTROL TOWER</text>
  <rect x="628" y="168" width="258" height="106" rx="14" fill="#0F172A" stroke="#F59E0B" stroke-width="1.2" />
  <text x="646" y="196" fill="#FBBF24" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="800">NDR ACTION REQUIRED · ATTEMPT #1</text>
  <text x="646" y="220" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">Consignee Unavailable</text>
  <rect x="646" y="234" width="106" height="26" rx="6" fill="#14532D" />
  <text x="699" y="251" text-anchor="middle" fill="#86EFAC" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">Re-Attempt</text>
  <rect x="762" y="234" width="106" height="26" rx="6" fill="#1E293B" stroke="#475569" />
  <text x="815" y="251" text-anchor="middle" fill="#E2E8F0" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">Edit Phone</text>
  <rect x="628" y="292" width="258" height="106" rx="14" fill="#0F172A" stroke="#38BDF8" stroke-width="1.2" />
  <text x="646" y="320" fill="#38BDF8" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="800">TEMPORAL WATCHDOG · 24/7</text>
  <text x="646" y="344" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">72h E-Way Bill Expiry Guard</text>
  <text x="646" y="368" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="12">Auto-flags high-value cargo &amp; missed</text>
  <text x="646" y="384" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="12">delivery slots before penalty accrual</text>
  <rect x="628" y="416" width="258" height="116" rx="14" fill="#0F172A" stroke="#334155" />
  <text x="646" y="444" fill="#4ADE80" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="800">RTO REDUCTION ENGINE</text>
  <text x="646" y="472" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="800">-38% RTO Rate</text>
  <text x="646" y="498" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="12">Instant shipper escalation &amp; alternate</text>
  <text x="646" y="514" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="12">consignee instructions before return</text>
</svg>`;

const WALLET_GST_BILLING_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600" viewBox="0 0 960 600" fill="none">
  <defs>
    <linearGradient id="bg4" x1="0" y1="0" x2="960" y2="600" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#0F172A" />
      <stop offset="55%" stop-color="#1E293B" />
      <stop offset="100%" stop-color="#0F172A" />
    </linearGradient>
    <pattern id="grid4" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#334155" stroke-width="0.7" stroke-opacity="0.45" />
    </pattern>
  </defs>
  <rect width="960" height="600" fill="url(#bg4)" />
  <rect width="960" height="600" fill="url(#grid4)" />
  <circle cx="800" cy="140" r="210" fill="#22C55E" fill-opacity="0.12" />
  <circle cx="160" cy="480" r="220" fill="#38BDF8" fill-opacity="0.1" />
  <rect x="48" y="38" width="864" height="54" rx="14" fill="#1E293B" stroke="#334155" stroke-width="1.5" />
  <circle cx="76" cy="65" r="6" fill="#22C55E" />
  <text x="92" y="70" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" letter-spacing="1">UNIFIED PREPAID WALLET · COD REMITTANCE &amp; GST BILLING ENGINE</text>
  <rect x="676" y="50" width="218" height="30" rx="8" fill="#0F172A" stroke="#475569" />
  <text x="785" y="70" text-anchor="middle" fill="#4ADE80" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">SAC 996812 / 996511 GST</text>
  <rect x="48" y="114" width="520" height="444" rx="20" fill="#1E293B" fill-opacity="0.95" stroke="#334155" stroke-width="1.5" />
  <rect x="76" y="142" width="464" height="114" rx="16" fill="#0F172A" stroke="#22C55E" stroke-width="1.5" />
  <text x="102" y="172" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" letter-spacing="1">AVAILABLE PREPAID WALLET BALANCE</text>
  <text x="102" y="214" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="34" font-weight="800">₹1,48,250.00</text>
  <text x="102" y="238" fill="#4ADE80" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">Instant UPI QR &amp; UTR Auto-Verification</text>
  <rect x="392" y="168" width="124" height="38" rx="10" fill="#14532D" stroke="#22C55E" />
  <text x="454" y="192" text-anchor="middle" fill="#FFFFFF" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="800">+ RECHARGE UPI</text>
  <text x="76" y="286" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" letter-spacing="1">ATOMIC LEDGER &amp; REPRICING AUDIT TRAIL</text>
  <rect x="76" y="302" width="464" height="66" rx="12" fill="#0F172A" stroke="#334155" />
  <text x="98" y="330" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">TAX INVOICE · LGSM/26-27/INV/00418</text>
  <text x="98" y="352" fill="#94A3B8" font-family="monospace" font-size="12">Booking Debit · AWB #LGSM84920143</text>
  <text x="516" y="340" text-anchor="end" fill="#F8FAFC" font-family="monospace" font-size="15" font-weight="800">-₹412.00</text>
  <rect x="76" y="380" width="464" height="66" rx="12" fill="#0F172A" stroke="#334155" />
  <text x="98" y="408" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">CREDIT NOTE · LGSM/26-27/CN/00092</text>
  <text x="98" y="430" fill="#94A3B8" font-family="monospace" font-size="12">Weight Dispute Approved · Auto-Refund</text>
  <text x="516" y="418" text-anchor="end" fill="#4ADE80" font-family="monospace" font-size="15" font-weight="800">+₹118.00</text>
  <rect x="76" y="458" width="464" height="72" rx="12" fill="#0F172A" stroke="#334155" />
  <text x="98" y="486" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">COD REMITTANCE · BATCH #REM-2026-084</text>
  <text x="98" y="508" fill="#38BDF8" font-family="monospace" font-size="12">NEFT UTR #HDFCN52026110499 · Settled to Bank</text>
  <text x="516" y="496" text-anchor="end" fill="#38BDF8" font-family="monospace" font-size="16" font-weight="800">₹64,900.00</text>
  <rect x="592" y="114" width="320" height="444" rx="20" fill="#1E293B" fill-opacity="0.95" stroke="#334155" stroke-width="1.5" />
  <text x="620" y="148" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" letter-spacing="1">FY-SCOPED GST DOCUMENT ENGINE</text>
  <rect x="620" y="168" width="264" height="118" rx="14" fill="#0F172A" stroke="#38BDF8" stroke-width="1.2" />
  <text x="640" y="196" fill="#38BDF8" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="800">18% GST PLACE-OF-SUPPLY SPLIT</text>
  <text x="640" y="224" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">Intra-State: 9% CGST + 9% SGST</text>
  <text x="640" y="248" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">Inter-State: 18% IGST</text>
  <text x="640" y="272" fill="#94A3B8" font-family="monospace" font-size="11">B2B GSTIN &amp; B2C Unregistered Ready</text>
  <rect x="620" y="304" width="264" height="112" rx="14" fill="#0F172A" stroke="#334155" />
  <text x="640" y="332" fill="#4ADE80" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="800">HSN / SAC CLASSIFICATION</text>
  <text x="640" y="358" fill="#F8FAFC" font-family="monospace" font-size="13" font-weight="700">SAC 996812 · Courier Express</text>
  <text x="640" y="382" fill="#F8FAFC" font-family="monospace" font-size="13" font-weight="700">SAC 996511 · Road Cargo GTA</text>
  <text x="640" y="402" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="11">Downloadable PDF Tax Invoices &amp; Notes</text>
  <rect x="620" y="432" width="264" height="98" rx="14" fill="#0F172A" stroke="#334155" />
  <text x="640" y="460" fill="#FBBF24" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="800">TRANSPARENT RATE CALCULATOR</text>
  <text x="640" y="486" fill="#F8FAFC" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700">Zero Hidden Surcharges</text>
  <text x="640" y="508" fill="#94A3B8" font-family="system-ui, -apple-system, sans-serif" font-size="12">Instant zone, fuel, COD &amp; FOV breakdown</text>
</svg>`;

export const B2C_EXPRESS_DATA_URI = toSvgDataUri(B2C_EXPRESS_SVG);
export const B2B_CARGO_FLEET_DATA_URI = toSvgDataUri(B2B_CARGO_FLEET_SVG);
export const HUB_SORTATION_DATA_URI = toSvgDataUri(HUB_SORTATION_SVG);
export const WALLET_GST_BILLING_DATA_URI = toSvgDataUri(WALLET_GST_BILLING_SVG);

/**
 * Maps legacy `/images/showcase/*.svg` file paths to their inline data URIs so
 * even if a tenant's saved `landing_page` config references those paths, the
 * browser never makes an HTTP request on load or slide rotation.
 */
export const SHOWCASE_SVG_DATA_URIS: Readonly<Record<string, string>> = {
  "/images/showcase/b2c-express.svg": B2C_EXPRESS_DATA_URI,
  "/images/showcase/b2b-cargo-fleet.svg": B2B_CARGO_FLEET_DATA_URI,
  "/images/showcase/hub-sortation.svg": HUB_SORTATION_DATA_URI,
  "/images/showcase/wallet-gst-billing.svg": WALLET_GST_BILLING_DATA_URI,
};
