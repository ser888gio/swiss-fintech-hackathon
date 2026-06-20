// Illustrative reference data — not a live sanctions feed.
// Tiers mirror the curated dataset in apps/api/app/tools/country_risk.py.

export type CountryTier = "blacklist" | "greylist";

export interface SanctionedCountry {
  code: string; // ISO 3166-1 alpha-2
  name: string;
  tier: CountryTier;
  rationale: string;
  sources: string[];
}

export interface BannedCompany {
  name: string;
  country: string;
  program: string;
  listedSince: string;
}

export interface SanctionedPerson {
  name: string;
  country: string;
  role: string;
  program: string;
  listedSince: string;
}

export const SANCTIONED_COUNTRIES: SanctionedCountry[] = [
  // ── Blacklist (FATF call for action) ─────────────────────────────────────
  {
    code: "IR",
    name: "Iran",
    tier: "blacklist",
    rationale: "FATF call for action; comprehensive OFAC sanctions program.",
    sources: ["FATF call for action", "OFAC Iran Sanctions Program"],
  },
  {
    code: "KP",
    name: "North Korea",
    tier: "blacklist",
    rationale: "FATF call for action; UN Security Council comprehensive sanctions.",
    sources: ["FATF call for action", "UN Security Council Sanctions"],
  },
  {
    code: "MM",
    name: "Myanmar",
    tier: "blacklist",
    rationale: "FATF call for action following 2021 military coup; significant financial crime risks.",
    sources: ["FATF call for action", "EU Restrictive Measures"],
  },
  // ── Greylist ─────────────────────────────────────────────────────────────
  {
    code: "RU",
    name: "Russia",
    tier: "greylist",
    rationale: "Broad EU, UK, and US sectoral sanctions following the 2022 invasion of Ukraine.",
    sources: ["EU Restrictive Measures", "OFAC Russia-related Sanctions"],
  },
  {
    code: "BY",
    name: "Belarus",
    tier: "greylist",
    rationale: "EU and US sectoral sanctions; enhanced due diligence required.",
    sources: ["EU Restrictive Measures", "OFAC Belarus Sanctions"],
  },
  {
    code: "SY",
    name: "Syria",
    tier: "greylist",
    rationale: "Comprehensive OFAC and EU sanctions; enhanced due diligence required.",
    sources: ["OFAC Syria Sanctions Program", "EU Restrictive Measures"],
  },
  {
    code: "CU",
    name: "Cuba",
    tier: "greylist",
    rationale: "Comprehensive OFAC embargo; transactions require specific OFAC licences.",
    sources: ["OFAC Cuba Sanctions Program"],
  },
  {
    code: "VE",
    name: "Venezuela",
    tier: "greylist",
    rationale: "OFAC sectoral sanctions targeting oil and financial sectors.",
    sources: ["OFAC Venezuela Sanctions Program"],
  },
  {
    code: "PK",
    name: "Pakistan",
    tier: "greylist",
    rationale: "FATF increased-monitoring list; enhanced due diligence applies.",
    sources: ["FATF increased monitoring"],
  },
  {
    code: "AF",
    name: "Afghanistan",
    tier: "greylist",
    rationale: "EU high-risk third country for strategic AML/CFT deficiencies.",
    sources: ["EU high-risk third country", "FATF increased monitoring"],
  },
  {
    code: "YE",
    name: "Yemen",
    tier: "greylist",
    rationale: "FATF increased-monitoring list; ongoing armed conflict raises ML/TF risks.",
    sources: ["FATF increased monitoring"],
  },
  {
    code: "HT",
    name: "Haiti",
    tier: "greylist",
    rationale: "FATF increased-monitoring list; weak governance and high corruption risk.",
    sources: ["FATF increased monitoring"],
  },
  {
    code: "ZW",
    name: "Zimbabwe",
    tier: "greylist",
    rationale: "Targeted EU and US sanctions; governance and corruption risks.",
    sources: ["OFAC Zimbabwe Sanctions Program", "EU Restrictive Measures"],
  },
  {
    code: "SS",
    name: "South Sudan",
    tier: "greylist",
    rationale: "EU high-risk third country with significant financial crime risks.",
    sources: ["EU high-risk third country"],
  },
  {
    code: "CD",
    name: "DR Congo",
    tier: "greylist",
    rationale: "EU high-risk third country designation.",
    sources: ["EU high-risk third country"],
  },
];

export const BANNED_COMPANIES: BannedCompany[] = [
  { name: "Arak Heavy Water Reactor Co.", country: "Iran", program: "OFAC Iran SDN", listedSince: "2012-01-23" },
  { name: "Korea Mining Development Corp (KOMID)", country: "North Korea", program: "UN 1718 Committee", listedSince: "2009-04-24" },
  { name: "Novatek OAO", country: "Russia", program: "OFAC SSI List", listedSince: "2014-07-16" },
  { name: "Rosneft PAO", country: "Russia", program: "EU Sectoral Sanctions", listedSince: "2014-09-12" },
  { name: "Almaz-Antey", country: "Russia", program: "OFAC SDN", listedSince: "2014-07-16" },
  { name: "General Petroleum Corp of Syria", country: "Syria", program: "OFAC Syria SDN", listedSince: "2011-08-18" },
  { name: "Cubaexport S.A.", country: "Cuba", program: "OFAC CACR", listedSince: "2004-03-01" },
  { name: "PDVSA (Petróleos de Venezuela)", country: "Venezuela", program: "OFAC EO 13884", listedSince: "2019-01-28" },
  { name: "Mahan Air", country: "Iran", program: "OFAC Iran SDN", listedSince: "2011-10-12" },
  { name: "Myawady Bank", country: "Myanmar", program: "OFAC Burma SDN", listedSince: "2021-04-07" },
  { name: "First Myanmar Investment", country: "Myanmar", program: "EU Restrictive Measures", listedSince: "2021-02-22" },
  { name: "KrasAvia", country: "Russia", program: "EU Aviation Sanctions", listedSince: "2022-03-01" },
  { name: "Belarusian Potash Company", country: "Belarus", program: "EU Sectoral Sanctions", listedSince: "2021-06-24" },
  { name: "National Development Bank of Zimbabwe", country: "Zimbabwe", program: "OFAC Zimbabwe SDN", listedSince: "2008-06-25" },
  { name: "Houthi-Aligned Yemen Import Corp.", country: "Yemen", program: "UN Yemen Panel", listedSince: "2020-01-15" },
];

export const SANCTIONED_PERSONS: SanctionedPerson[] = [
  { name: "Ali Khamenei", country: "Iran", role: "Supreme Leader", program: "OFAC Iran SDN", listedSince: "2019-06-24" },
  { name: "Kim Jong-un", country: "North Korea", role: "Head of State", program: "UN 1718 Committee", listedSince: "2016-03-02" },
  { name: "Min Aung Hlaing", country: "Myanmar", role: "Commander-in-Chief", program: "EU/OFAC Burma SDN", listedSince: "2021-02-11" },
  { name: "Igor Sechin", country: "Russia", role: "Rosneft CEO", program: "OFAC SDN", listedSince: "2014-04-28" },
  { name: "Sergei Lavrov", country: "Russia", role: "Foreign Minister", program: "EU Restrictive Measures", listedSince: "2022-02-25" },
  { name: "Alexander Lukashenko", country: "Belarus", role: "President", program: "EU/OFAC SDN", listedSince: "2020-10-06" },
  { name: "Nicolás Maduro", country: "Venezuela", role: "President", program: "OFAC EO 13692", listedSince: "2017-07-26" },
  { name: "Bashar al-Assad", country: "Syria", role: "President", program: "OFAC Syria SDN", listedSince: "2011-05-18" },
  { name: "Emad Khamis", country: "Syria", role: "Former PM", program: "EU Restrictive Measures", listedSince: "2014-03-14" },
  { name: "Qasem Soleimani (estate)", country: "Iran", role: "Former IRGC-QF Commander", program: "OFAC Iran SDN", listedSince: "2011-06-05" },
  { name: "Choe Ryong-hae", country: "North Korea", role: "State Affairs Commission", program: "UN 1718 Committee", listedSince: "2014-03-07" },
  { name: "Thida Oo", country: "Myanmar", role: "Attorney General", program: "OFAC Burma SDN", listedSince: "2022-03-25" },
  { name: "Delfín Noel Chávez Torrealba", country: "Venezuela", role: "State Oil Official", program: "OFAC EO 13808", listedSince: "2019-07-22" },
  { name: "Emmerson Mnangagwa", country: "Zimbabwe", role: "President", program: "EU Targeted Sanctions", listedSince: "2002-02-18" },
  { name: "Abdul-Malik al-Houthi", country: "Yemen", role: "Houthi Leader", program: "UN Yemen Sanctions", listedSince: "2015-07-14" },
];
