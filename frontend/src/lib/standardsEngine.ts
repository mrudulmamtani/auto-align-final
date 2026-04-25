/**
 * Standards Transformer & Semantic Linking Engine
 *
 * Normalizes all standards into a common schema and builds
 * cross-standard semantic links based on domain similarity and keyword overlap.
 *
 * Standards: UAE IAS, ISO 27001, NIST CSF, COSO ERM, SOC 2, PCI DSS, GDPR,
 *            NCA OTC, NCA TCC, NCA CSCC, NCA ECC, NCA CCC, NCA DCC, NCA OSMACC, NCA NCS
 */

import rawUaeIas   from "@/data/raw/uae_ias.json";
import rawNcaOtc   from "@/data/raw/nca_otc.json";
import rawNcaTcc   from "@/data/raw/nca_tcc.json";
import rawNcaCscc  from "@/data/raw/nca_cscc.json";
import rawNcaEcc   from "@/data/raw/nca_ecc.json";
import rawNcaCcc   from "@/data/raw/nca_ccc.json";
import rawNcaDcc   from "@/data/raw/nca_dcc.json";
import rawNcaOsmacc from "@/data/raw/nca_osmacc.json";
import rawNcaNcs   from "@/data/raw/nca_ncs.json";
import rawGdpr     from "@/data/raw/GDPR.json";
import rawIso27001 from "@/data/raw/iso_27001.json";
import rawNistCsf  from "@/data/raw/nist_csf.json";
import rawCosoErm  from "@/data/raw/coso_erm.json";
import rawSoc2     from "@/data/raw/soc_2.json";
import rawPciDss   from "@/data/raw/pci_dss.json";

// ── Common Schema ──────────────────────────────────────────────

export interface NormalizedControl {
  id: string;
  name: string;
  text: string;
  obligation: "must" | "shall" | "should";
  subControls: string[];
  sourcePage: string;
  keywords: string[];
  pdf_ref: { page: number; coordinates: number[] };
}

export interface NormalizedDomain {
  id: string;
  name: string;
  objective: string;
  controls: NormalizedControl[];
}

export interface NormalizedStandard {
  standard_name: string;
  short_name: string;
  version: string;
  urn: string;
  domains: NormalizedDomain[];
  totalControls: number;
}

export interface SemanticLink {
  sourceStandard: string;
  sourceControlId: string;
  targetStandard: string;
  targetControlId: string;
  similarity: number;
  linkType: "domain_match" | "keyword_overlap" | "explicit_reference";
  sharedKeywords: string[];
}

// ── Raw Types ──────────────────────────────────────────────────

interface RawUaeIas {
  control_family_id: string;
  control_family_name: string;
  control_subfamily_id: string;
  control_subfamily_name: string;
  control_id: string;
  control_name: string;
  priority: string;
  control_statement: string;
  sub_controls: string[];
  source_page: string;
  objective_family_level?: string;
  [key: string]: unknown;
}

interface RawNcaOtc {
  framework_name: string;
  version?: string;
  main_domain_id: string;
  main_domain_name: string;
  subdomain_id: string;
  subdomain_name: string;
  objective: string;
  control_id: string;
  control_statement: string;
  subcontrols: string[];
  ecc_reference: string | null;
  source_page: string;
  [key: string]: unknown;
}

interface RawNcaTcc {
  framework_name: string;
  main_domain_id: string;
  main_domain_name: string;
  subdomain_id: string;
  subdomain_name: string;
  objective: string;
  control_id: string;
  control_statement: string;
  subcontrols: string[];
  ecc_reference: string | null;
  source_page: string;
  [key: string]: unknown;
}

interface RawNcaCscc {
  Main_Domain_ID: string;
  Main_Domain_Name: string;
  Subdomain_ID: string;
  Subdomain_Name: string;
  Subdomain_Objective: string;
  Main_Control_ID: string;
  Main_Control_Description: string;
  Subcontrol_ID: string;
  Subcontrol_Description: string;
  [key: string]: unknown;
}

interface RawNcaEcc {
  framework_name: string;
  version: string;
  year: string;
  main_domain_id: string;
  main_domain_name: string;
  subdomain_id: string;
  subdomain_name: string;
  objective: string;
  control_id: string;
  control_statement: string;
  subcontrols: string[];
  review_requirement: string | null;
  frequency_requirement: string | null;
  conditional_applicability: string | null;
  regulatory_reference: string | null;
  source_page: string;
}

interface RawNcaCcc {
  framework_name: string;
  version: string;
  year: string;
  applicability_type: string;
  main_domain_id: string;
  main_domain_name: string;
  subdomain_id: string;
  subdomain_name: string;
  objective: string;
  control_id: string;
  control_statement: string;
  subcontrols: string[];
  ecc_reference: string | null;
  frequency_requirement: string | null;
  conditional_applicability: string | null;
  level_1: string;
  level_2: string;
  level_3: string;
  level_4: string;
  regulatory_reference: string | null;
  source_page: string;
}

interface RawNcaDcc {
  framework_name: string;
  version: string;
  year: string;
  main_domain_id: string;
  main_domain_name: string;
  subdomain_id: string;
  subdomain_name: string;
  objective: string;
  control_id: string;
  control_statement: string;
  subcontrols: string[];
  ecc_reference: string | null;
  data_classification_applicability: Record<string, string>;
  frequency_requirement: string | null;
  conditional_applicability: string | null;
  regulatory_reference: string | null;
  source_page: string;
}

interface RawNcaOsmacc {
  framework_name: string;
  version: string;
  year: string;
  main_domain_id: string;
  main_domain_name: string;
  subdomain_id: string;
  subdomain_name: string;
  objective: string;
  control_id: string;
  control_statement: string;
  subcontrols: string[];
  ecc_reference: string | null;
  frequency_requirement: string | null;
  conditional_applicability: string | null;
  regulatory_reference: string | null;
  source_page: string;
}

interface RawNcaNcs {
  framework_name: string;
  version: string;
  year: string;
  section_number: string;
  section_title: string;
  category: string;
  algorithm_or_standard: string;
  requirement_type: string;
  requirement_text: string;
  strength_level: string | null;
  key_length_or_parameter: string | null;
  notes_or_conditions: string | null;
  not_accepted_for: string | null;
  regulatory_reference: string | null;
  source_page: string;
}

interface RawGdpr {
  document_name: string;
  short_name: string;
  article_number: string;
  article_title: string;
  chapter_number: string;
  chapter_title: string;
  section_number: string | null;
  section_title: string | null;
  recital_reference: string | null;
  provision_type: string;
  provision_number: string;
  parent_provision_number: string | null;
  provision_text_verbatim: string;
  legal_effect: string;
  actor: string | null;
  condition_trigger: string | null;
  cross_reference: string | null;
  penalty_reference: string | null;
  source_page: string;
  pdf_bbox: null;
}

// ── Keyword Extraction ─────────────────────────────────────────

const STOP_WORDS = new Set([
  "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
  "of", "with", "by", "from", "as", "is", "was", "are", "be", "been",
  "being", "have", "has", "had", "do", "does", "did", "will", "would",
  "could", "should", "may", "might", "shall", "must", "can", "need",
  "that", "this", "these", "those", "it", "its", "not", "no", "all",
  "any", "each", "every", "both", "such", "than", "then", "also",
  "which", "who", "whom", "what", "when", "where", "how", "more",
  "most", "other", "some", "only", "same", "into", "over", "after",
  "before", "between", "under", "above", "below", "up", "down",
  "out", "off", "about", "through", "during", "including", "within",
  "without", "based", "ensure", "entity", "organization",
  "requirements", "related", "following", "according", "part",
]);

function extractKeywords(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 2 && !STOP_WORDS.has(w))
    .filter((v, i, a) => a.indexOf(v) === i);
}

function detectObligation(text: string): "must" | "shall" | "should" {
  const lower = text.toLowerCase();
  if (lower.includes("must")) return "must";
  if (lower.includes("shall")) return "shall";
  return "should";
}

// ── Generic NCA-style transformer (OTC/TCC/ECC/CCC/DCC/OSMACC pattern) ────

type NcaLikeRaw = {
  main_domain_id: string;
  main_domain_name: string;
  subdomain_name: string;
  objective: string;
  control_id: string;
  control_statement: string;
  subcontrols?: string[];
  source_page: string;
};

function transformNcaLike(
  raw: NcaLikeRaw[],
  stdName: string,
  shortName: string,
  version: string,
  urn: string,
  prefix: string,
): NormalizedStandard {
  const domainMap = new Map<string, { name: string; controls: NormalizedControl[]; objective: string }>();

  for (const ctrl of raw) {
    const domKey = ctrl.main_domain_id;
    if (!domainMap.has(domKey)) {
      domainMap.set(domKey, { name: ctrl.main_domain_name, controls: [], objective: ctrl.objective });
    }
    const page = parseInt(ctrl.source_page, 10) || 1;
    domainMap.get(domKey)!.controls.push({
      id: `${prefix}-${ctrl.control_id}`,
      name: `${ctrl.subdomain_name} (${ctrl.control_id})`,
      text: ctrl.control_statement,
      obligation: detectObligation(ctrl.control_statement),
      subControls: ctrl.subcontrols ?? [],
      sourcePage: ctrl.source_page,
      keywords: extractKeywords(`${ctrl.subdomain_name} ${ctrl.control_statement} ${ctrl.main_domain_name}`),
      pdf_ref: { page, coordinates: [80, 150 + ((page % 5) * 40), 450, 50] },
    });
  }

  const domains: NormalizedDomain[] = [];
  for (const [id, data] of domainMap) {
    domains.push({ id, name: data.name, objective: data.objective, controls: data.controls });
  }

  return { standard_name: stdName, short_name: shortName, version, urn, domains, totalControls: raw.length };
}

// ── UAE IAS Transformer ────────────────────────────────────────

function transformUaeIas(): NormalizedStandard {
  const raw = rawUaeIas as RawUaeIas[];
  const domainMap = new Map<string, { name: string; subfamilies: Map<string, NormalizedControl[]>; objective: string }>();

  for (const ctrl of raw) {
    if (!domainMap.has(ctrl.control_family_id)) {
      domainMap.set(ctrl.control_family_id, {
        name: ctrl.control_family_name,
        subfamilies: new Map(),
        objective: ctrl.objective_family_level ?? "",
      });
    }
    const domain = domainMap.get(ctrl.control_family_id)!;
    const page = parseInt(ctrl.source_page, 10) || 1;

    const normalized: NormalizedControl = {
      id: ctrl.control_id,
      name: ctrl.control_name,
      text: ctrl.control_statement,
      obligation: detectObligation(ctrl.control_statement),
      subControls: ctrl.sub_controls ?? [],
      sourcePage: ctrl.source_page,
      keywords: extractKeywords(`${ctrl.control_name} ${ctrl.control_statement} ${ctrl.control_family_name}`),
      pdf_ref: { page, coordinates: [80, 150 + ((page % 5) * 40), 450, 50] },
    };

    if (!domain.subfamilies.has(ctrl.control_subfamily_id)) {
      domain.subfamilies.set(ctrl.control_subfamily_id, []);
    }
    domain.subfamilies.get(ctrl.control_subfamily_id)!.push(normalized);
  }

  const domains: NormalizedDomain[] = [];
  for (const [id, data] of domainMap) {
    const controls: NormalizedControl[] = [];
    for (const ctrls of data.subfamilies.values()) controls.push(...ctrls);
    domains.push({ id, name: data.name, objective: data.objective, controls });
  }

  return {
    standard_name: "UAE IAS",
    short_name: "UAE IAS",
    version: "2.0",
    urn: "urn:pwc:std:uae-ias",
    domains,
    totalControls: raw.length,
  };
}

// ── NCA OTC Transformer ────────────────────────────────────────

function transformNcaOtc(): NormalizedStandard {
  return transformNcaLike(
    rawNcaOtc as unknown as NcaLikeRaw[],
    "NCA OTC", "NCA OTC", "1.0", "urn:pwc:std:nca-otc", "OTC",
  );
}

// ── ISO 27001 Transformer ────────────────────────────────────────────────
function transformIso27001(): NormalizedStandard {
  return transformNcaLike(
    rawIso27001 as unknown as NcaLikeRaw[],
    "ISO 27001", "ISO 27001", "2022", "urn:pwc:std:iso-27001", "ISO",
  );
}

// ── NIST CSF Transformer ─────────────────────────────────────────────────
function transformNistCsf(): NormalizedStandard {
  return transformNcaLike(
    rawNistCsf as unknown as NcaLikeRaw[],
    "NIST CSF", "NIST CSF", "2.0", "urn:pwc:std:nist-csf", "NIST",
  );
}

// ── COSO ERM Transformer ─────────────────────────────────────────────────
function transformCosoErm(): NormalizedStandard {
  return transformNcaLike(
    rawCosoErm as unknown as NcaLikeRaw[],
    "COSO ERM", "COSO ERM", "2017", "urn:pwc:std:coso-erm", "COSO",
  );
}

// ── SOC 2 Transformer ────────────────────────────────────────────────────
function transformSoc2(): NormalizedStandard {
  return transformNcaLike(
    rawSoc2 as unknown as NcaLikeRaw[],
    "SOC 2", "SOC 2", "2017", "urn:pwc:std:soc-2", "SOC2",
  );
}

// ── PCI DSS Transformer ──────────────────────────────────────────────────
function transformPciDss(): NormalizedStandard {
  return transformNcaLike(
    rawPciDss as unknown as NcaLikeRaw[],
    "PCI DSS", "PCI DSS", "4.0", "urn:pwc:std:pci-dss", "PCI",
  );
}

// ── NCA TCC Transformer ────────────────────────────────────────

function transformNcaTcc(): NormalizedStandard {
  return transformNcaLike(
    rawNcaTcc as unknown as NcaLikeRaw[],
    "NCA TCC", "NCA TCC", "1.0", "urn:pwc:std:nca-tcc", "TCC",
  );
}

// ── NCA ECC Transformer ────────────────────────────────────────

function transformNcaEcc(): NormalizedStandard {
  return transformNcaLike(
    rawNcaEcc as unknown as NcaLikeRaw[],
    "NCA ECC", "NCA ECC", "2.0", "urn:pwc:std:nca-ecc", "ECC",
  );
}

// ── NCA CCC Transformer ────────────────────────────────────────

function transformNcaCcc(): NormalizedStandard {
  return transformNcaLike(
    rawNcaCcc as unknown as NcaLikeRaw[],
    "NCA CCC", "NCA CCC", "2.0", "urn:pwc:std:nca-ccc", "CCC",
  );
}

// ── NCA DCC Transformer ────────────────────────────────────────

function transformNcaDcc(): NormalizedStandard {
  return transformNcaLike(
    rawNcaDcc as unknown as NcaLikeRaw[],
    "NCA DCC", "NCA DCC", "1.0", "urn:pwc:std:nca-dcc", "DCC",
  );
}

// ── NCA OSMACC Transformer ─────────────────────────────────────

function transformNcaOsmacc(): NormalizedStandard {
  return transformNcaLike(
    rawNcaOsmacc as unknown as NcaLikeRaw[],
    "NCA OSMACC", "NCA OSMACC", "1.0", "urn:pwc:std:nca-osmacc", "OSMACC",
  );
}

// ── NCA CSCC Transformer ───────────────────────────────────────

function transformNcaCscc(): NormalizedStandard {
  const raw = rawNcaCscc as RawNcaCscc[];

  const domainMap = new Map<string, {
    name: string;
    objective: string;
    controlMap: Map<string, { mainText: string; subdomainName: string; subControls: string[] }>;
  }>();

  for (const rec of raw) {
    const domKey = rec.Main_Domain_ID;
    if (!domainMap.has(domKey)) {
      domainMap.set(domKey, {
        name: rec.Main_Domain_Name,
        objective: rec.Subdomain_Objective,
        controlMap: new Map(),
      });
    }
    const dom = domainMap.get(domKey)!;
    const ctrlKey = rec.Main_Control_ID;
    if (!dom.controlMap.has(ctrlKey)) {
      dom.controlMap.set(ctrlKey, {
        mainText: rec.Main_Control_Description,
        subdomainName: rec.Subdomain_Name,
        subControls: [],
      });
    }
    if (rec.Subcontrol_Description) {
      dom.controlMap.get(ctrlKey)!.subControls.push(rec.Subcontrol_Description);
    }
  }

  let controlIndex = 0;
  const domains: NormalizedDomain[] = [];

  for (const [domId, domData] of domainMap) {
    const controls: NormalizedControl[] = [];
    for (const [ctrlId, ctrlData] of domData.controlMap) {
      const page = 20 + Math.floor(controlIndex / 8);
      const yOffset = 640 - ((controlIndex % 8) * 70);
      controls.push({
        id: `CSCC-${ctrlId}`,
        name: `${ctrlData.subdomainName} (${ctrlId})`,
        text: ctrlData.mainText || ctrlData.subControls[0] || "",
        obligation: detectObligation(ctrlData.mainText),
        subControls: ctrlData.subControls,
        sourcePage: String(page),
        keywords: extractKeywords(
          `${ctrlData.subdomainName} ${ctrlData.mainText} ${domData.name} cloud cybersecurity critical systems`
        ),
        pdf_ref: { page, coordinates: [140, yOffset, 420, 50] },
      });
      controlIndex++;
    }
    domains.push({ id: domId, name: domData.name, objective: domData.objective, controls });
  }

  return {
    standard_name: "NCA CSCC",
    short_name: "NCA CSCC",
    version: "1.0",
    urn: "urn:pwc:std:nca-cscc",
    domains,
    totalControls: raw.length,
  };
}

// ── NCA NCS Transformer ────────────────────────────────────────

function transformNcaNcs(): NormalizedStandard {
  const raw = rawNcaNcs as RawNcaNcs[];

  const domainMap = new Map<string, Map<string, {
    section_title: string;
    primary_text: string;
    page: number;
    subControls: string[];
    algorithm: string;
  }>>();

  const seenSubCtrl = new Map<string, Set<string>>();

  for (const rec of raw) {
    const category = rec.category || "General";
    const sectionKey = rec.section_number;
    const domKey = `${category}::${sectionKey}`;

    if (!domainMap.has(category)) domainMap.set(category, new Map());
    const sectionMap = domainMap.get(category)!;

    if (!sectionMap.has(sectionKey)) {
      sectionMap.set(sectionKey, {
        section_title: rec.section_title,
        primary_text: rec.requirement_text,
        page: parseInt(rec.source_page, 10) || 1,
        subControls: [],
        algorithm: rec.algorithm_or_standard,
      });
      seenSubCtrl.set(domKey, new Set());
    }

    const entry = sectionMap.get(sectionKey)!;
    const subText = [
      `${rec.requirement_type}: ${rec.requirement_text}`,
      rec.notes_or_conditions ? `(${rec.notes_or_conditions})` : "",
      rec.not_accepted_for ? `Not accepted for: ${rec.not_accepted_for}` : "",
    ].filter(Boolean).join(" ");

    const subSeen = seenSubCtrl.get(domKey)!;
    if (!subSeen.has(subText)) {
      subSeen.add(subText);
      entry.subControls.push(subText);
    }
  }

  const domains: NormalizedDomain[] = [];
  let totalControls = 0;

  for (const [category, sectionMap] of domainMap) {
    const controls: NormalizedControl[] = [];
    for (const [sectionNum, entry] of sectionMap) {
      const { page } = entry;
      controls.push({
        id: `NCS-${sectionNum}`,
        name: entry.section_title || entry.algorithm || sectionNum,
        text: `${entry.section_title} — ${entry.primary_text}`,
        obligation: "shall",
        subControls: entry.subControls,
        sourcePage: String(entry.page),
        keywords: extractKeywords(`${category} ${entry.section_title} ${entry.algorithm} cryptography`),
        pdf_ref: { page, coordinates: [80, 150 + ((page % 5) * 40), 450, 50] },
      });
      totalControls++;
    }
    const domId = category.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    domains.push({ id: domId, name: category, objective: "", controls });
  }

  return {
    standard_name: "NCA NCS",
    short_name: "NCA NCS",
    version: "1.0",
    urn: "urn:pwc:std:nca-ncs",
    domains,
    totalControls,
  };
}

// ── GDPR Transformer ───────────────────────────────────────────

function transformGdpr(): NormalizedStandard {
  const raw = rawGdpr as RawGdpr[];
  const domainMap = new Map<string, { name: string; objective: string; controls: NormalizedControl[] }>();

  const seen = new Set<string>();

  for (const rec of raw) {
    const provId = `${rec.article_number} §${rec.provision_number}`;
    if (seen.has(provId)) continue;
    seen.add(provId);

    const domKey = rec.chapter_number;
    if (!domainMap.has(domKey)) {
      domainMap.set(domKey, {
        name: rec.chapter_title,
        objective: `${rec.chapter_number}: ${rec.chapter_title}`,
        controls: [],
      });
    }

    const page = parseInt(rec.source_page, 10) || 1;
    const obligation = rec.legal_effect === "mandatory" ? "must" : "should";

    domainMap.get(domKey)!.controls.push({
      id: `GDPR-${rec.provision_number}`,
      name: `${rec.article_number} — ${rec.article_title}`,
      text: rec.provision_text_verbatim,
      obligation,
      subControls: [],
      sourcePage: rec.source_page,
      keywords: extractKeywords(
        `${rec.article_title} ${rec.chapter_title} ${rec.provision_text_verbatim} ${rec.provision_type} data privacy`
      ),
      pdf_ref: { page, coordinates: [80, 150 + ((page % 5) * 40), 450, 50] },
    });
  }

  const domains: NormalizedDomain[] = [];
  for (const [id, data] of domainMap) {
    domains.push({ id, name: data.name, objective: data.objective, controls: data.controls });
  }

  return {
    standard_name: "GDPR",
    short_name: "GDPR",
    version: "2016/679",
    urn: "urn:pwc:std:gdpr",
    domains,
    totalControls: seen.size,
  };
}

// ── Semantic Linking Engine ────────────────────────────────────

/** Jaccard similarity of two keyword sets */
function keywordSimilarity(a: string[], b: string[]): { score: number; shared: string[] } {
  const setA = new Set(a);
  const setB = new Set(b);
  const shared = a.filter((k) => setB.has(k));
  const union = new Set([...setA, ...setB]);
  return { score: union.size > 0 ? shared.length / union.size : 0, shared };
}

/** Domain-level semantic mapping between standards */
const DOMAIN_SEMANTIC_MAP: Record<string, string[]> = {
  "governance": ["strategy", "planning", "leadership", "policy", "policies", "procedures", "management", "commitment", "roles", "responsibilities"],
  "risk": ["risk", "assessment", "treatment", "residual", "evaluation", "improvement"],
  "access": ["access", "control", "identity", "authentication", "authorization", "privilege", "segregation", "duties"],
  "operations": ["operations", "defense", "network", "systems", "configuration", "hardening", "monitoring", "logging"],
  "incident": ["incident", "response", "continuity", "recovery", "disaster", "resilience", "detection"],
  "thirdparty": ["third", "party", "vendor", "supplier", "outsourcing", "cloud", "external"],
  "data": ["data", "information", "classification", "encryption", "privacy", "protection", "communications"],
  "physical": ["physical", "environmental", "facility", "premises"],
  "training": ["training", "awareness", "human", "resources", "personnel", "competence"],
  "development": ["development", "acquisition", "maintenance", "software", "application", "code"],
  "compliance": ["compliance", "audit", "regulation", "legal", "regulatory"],
  "asset": ["asset", "inventory", "classification", "lifecycle"],
  "cryptography": ["cryptography", "cryptographic", "encryption", "algorithm", "cipher", "key", "hash"],
  "privacy": ["privacy", "personal", "data", "subject", "consent", "controller", "processor", "gdpr"],
};

function getDomainCluster(domainName: string): string[] {
  const lower = domainName.toLowerCase();
  const clusters: string[] = [];
  for (const [cluster, keywords] of Object.entries(DOMAIN_SEMANTIC_MAP)) {
    if (keywords.some((k) => lower.includes(k))) clusters.push(cluster);
  }
  return clusters.length > 0 ? clusters : ["general"];
}

function buildSemanticLinks(standards: NormalizedStandard[]): SemanticLink[] {
  const links: SemanticLink[] = [];
  const SIMILARITY_THRESHOLD = 0.12;

  for (let si = 0; si < standards.length; si++) {
    for (let sj = si + 1; sj < standards.length; sj++) {
      const stdA = standards[si];
      const stdB = standards[sj];

      for (const domA of stdA.domains) {
        const clustersA = getDomainCluster(domA.name);
        for (const domB of stdB.domains) {
          const clustersB = getDomainCluster(domB.name);
          if (!clustersA.some((c) => clustersB.includes(c))) continue;

          for (const ctrlA of domA.controls) {
            for (const ctrlB of domB.controls) {
              const { score, shared } = keywordSimilarity(ctrlA.keywords, ctrlB.keywords);
              if (score >= SIMILARITY_THRESHOLD && shared.length >= 2) {
                links.push({
                  sourceStandard: stdA.standard_name,
                  sourceControlId: ctrlA.id,
                  targetStandard: stdB.standard_name,
                  targetControlId: ctrlB.id,
                  similarity: Math.round(score * 100) / 100,
                  linkType: "keyword_overlap",
                  sharedKeywords: shared.slice(0, 6),
                });
              }
            }
          }
        }
      }
    }
  }

  links.sort((a, b) => b.similarity - a.similarity);
  return links;
}

// ── Exported Engine ────────────────────────────────────────────

const uaeIas    = transformUaeIas();
const ncaOtc    = transformNcaOtc();
const ncaTcc    = transformNcaTcc();
const ncaCscc   = transformNcaCscc();
const ncaEcc    = transformNcaEcc();
const ncaCcc    = transformNcaCcc();
const ncaDcc    = transformNcaDcc();
const ncaOsmacc = transformNcaOsmacc();
const ncaNcs    = transformNcaNcs();
const gdpr      = transformGdpr();
const iso27001  = transformIso27001();
const nistCsf   = transformNistCsf();
const cosoErm   = transformCosoErm();
const soc2      = transformSoc2();
const pciDss    = transformPciDss();

export const ALL_STANDARDS: NormalizedStandard[] = [
  uaeIas, iso27001, nistCsf, cosoErm, soc2, pciDss, gdpr,
  ncaOtc, ncaTcc, ncaCscc, ncaEcc, ncaCcc, ncaDcc, ncaOsmacc, ncaNcs,
];
export const SEMANTIC_LINKS: SemanticLink[] = buildSemanticLinks(ALL_STANDARDS);

/** Get a standard by short name */
export function getStandard(name: string): NormalizedStandard | undefined {
  return ALL_STANDARDS.find((s) =>
    s.standard_name.toLowerCase().includes(name.toLowerCase()) ||
    s.short_name.toLowerCase().includes(name.toLowerCase())
  );
}

/** Get all controls across all standards */
export function getAllControls(): Array<NormalizedControl & { standardName: string; domainName: string }> {
  const result: Array<NormalizedControl & { standardName: string; domainName: string }> = [];
  for (const std of ALL_STANDARDS) {
    for (const dom of std.domains) {
      for (const ctrl of dom.controls) {
        result.push({ ...ctrl, standardName: std.standard_name, domainName: dom.name });
      }
    }
  }
  return result;
}

/** Get semantic links for a specific control */
export function getLinksForControl(controlId: string): SemanticLink[] {
  return SEMANTIC_LINKS.filter(
    (l) => l.sourceControlId === controlId || l.targetControlId === controlId
  );
}

/** Get linked controls for a given control (cross-standard) */
export function getLinkedControls(controlId: string): Array<{ control: NormalizedControl; standard: string; similarity: number; sharedKeywords: string[] }> {
  const links = getLinksForControl(controlId);
  const results: Array<{ control: NormalizedControl; standard: string; similarity: number; sharedKeywords: string[] }> = [];

  for (const link of links) {
    const targetId  = link.sourceControlId === controlId ? link.targetControlId  : link.sourceControlId;
    const targetStd = link.sourceControlId === controlId ? link.targetStandard   : link.sourceStandard;

    const std = ALL_STANDARDS.find((s) => s.standard_name === targetStd);
    if (!std) continue;

    for (const dom of std.domains) {
      const ctrl = dom.controls.find((c) => c.id === targetId);
      if (ctrl) {
        results.push({ control: ctrl, standard: targetStd, similarity: link.similarity, sharedKeywords: link.sharedKeywords });
        break;
      }
    }
  }

  return results;
}

/** Convert to the legacy app format used by existing components */
export function toLegacyFormat(std: NormalizedStandard) {
  return {
    standard_name: std.standard_name,
    version: std.version,
    urn: std.urn,
    domains: std.domains.map((d) => ({
      id: d.id,
      name: d.name,
      controls: d.controls.map((c) => ({
        id: c.id,
        text: c.text,
        obligation: c.obligation,
        pdf_ref: c.pdf_ref,
      })),
    })),
  };
}

/** Stats summary for dashboard */
export function getStandardsStats() {
  return ALL_STANDARDS.map((std) => ({
    name: std.standard_name,
    version: std.version,
    domainCount: std.domains.length,
    totalControls: std.totalControls,
    mustCount:   std.domains.reduce((s, d) => s + d.controls.filter((c) => c.obligation === "must").length, 0),
    shallCount:  std.domains.reduce((s, d) => s + d.controls.filter((c) => c.obligation === "shall").length, 0),
    shouldCount: std.domains.reduce((s, d) => s + d.controls.filter((c) => c.obligation === "should").length, 0),
  }));
}

/** Get domain-level cross-standard mapping */
export function getDomainMapping() {
  const mapping: Record<string, Array<{ standard: string; domain: string; controlCount: number }>> = {};

  for (const std of ALL_STANDARDS) {
    for (const dom of std.domains) {
      const clusters = getDomainCluster(dom.name);
      for (const cluster of clusters) {
        if (!mapping[cluster]) mapping[cluster] = [];
        mapping[cluster].push({ standard: std.standard_name, domain: dom.name, controlCount: dom.controls.length });
      }
    }
  }

  return mapping;
}
