// Display metadata only (id/icon/name/desc/category). Badge ELIGIBILITY is
// decided authoritatively by the Flask backend (server/badges.py) via
// GET /api/badges/me (the signed-in user's own badges) and GET /api/leaderboard
// (every row's badge_count) - this file must not re-derive eligibility from
// scans, since that would let client and server logic drift apart. Badge ids
// below must stay in lockstep with the ids in server/badges.py.

export const BADGES = [
  // — Scanning milestones
  { id: "scan_1",     icon: "🔍", name: "First Scan",           desc: "Scan your very first coin",          category: "Scanning" },
  { id: "scan_10",    icon: "🔟", name: "Getting Started",      desc: "Scan 10 coins",                      category: "Scanning" },
  { id: "scan_25",    icon: "⭐", name: "Coin Enthusiast",      desc: "Scan 25 coins",                      category: "Scanning" },
  { id: "scan_50",    icon: "🏆", name: "Half Century",         desc: "Scan 50 coins",                      category: "Scanning" },
  { id: "scan_100",   icon: "💯", name: "Century Club",         desc: "Scan 100 coins",                     category: "Scanning" },
  { id: "scan_250",   icon: "🚀", name: "Dedicated Collector",  desc: "Scan 250 coins",                     category: "Scanning" },
  { id: "scan_500",   icon: "👑", name: "Master Scanner",       desc: "Scan 500 coins",                     category: "Scanning" },
  { id: "scan_1000",  icon: "🔱", name: "Elite Collector",      desc: "Scan 1,000 coins",                   category: "Scanning" },
  { id: "scan_2500",  icon: "🌌", name: "Numismatic Legend",    desc: "Scan 2,500 coins",                   category: "Scanning" },
  { id: "scan_5000",  icon: "⚡", name: "Coin Overlord",        desc: "Scan 5,000 coins",                   category: "Scanning" },
  { id: "scan_10000", icon: "🌠", name: "The Archivist",        desc: "Scan 10,000 coins",                  category: "Scanning" },
  // — Net worth milestones
  { id: "worth_1",      icon: "💰", name: "First Dollar",       desc: "Reach $1 in collection value",       category: "Net Worth" },
  { id: "worth_10",     icon: "💵", name: "Growing Stack",      desc: "Reach $10 in collection value",      category: "Net Worth" },
  { id: "worth_50",     icon: "💸", name: "Rising Value",       desc: "Reach $50 in collection value",      category: "Net Worth" },
  { id: "worth_100",    icon: "🤑", name: "Century Mark",       desc: "Reach $100 in collection value",     category: "Net Worth" },
  { id: "worth_500",    icon: "💎", name: "Five Hundred",       desc: "Reach $500 in collection value",     category: "Net Worth" },
  { id: "worth_1000",   icon: "🏦", name: "Four Figures",       desc: "Reach $1,000 in collection value",   category: "Net Worth" },
  { id: "worth_10000",  icon: "🌟", name: "High Roller",        desc: "Reach $10,000 in collection value",  category: "Net Worth" },
  { id: "worth_25000",  icon: "🔥", name: "Quarter Million",    desc: "Reach $25,000 in collection value",  category: "Net Worth" },
  { id: "worth_100000", icon: "🏅", name: "Six Figures",        desc: "Reach $100,000 in collection value", category: "Net Worth" },
  { id: "worth_500000", icon: "🦅", name: "Half Million",       desc: "Reach $500,000 in collection value", category: "Net Worth" },
  { id: "worth_1m",     icon: "👁️", name: "The Million",        desc: "Reach $1,000,000 in collection value",category:"Net Worth" },
  // — Membership milestones
  { id: "mem_join", icon: "👋", name: "Welcome",                desc: "Join CoinLens",                      category: "Member" },
  { id: "mem_7",    icon: "📅", name: "One Week",               desc: "Be a member for 7 days",             category: "Member" },
  { id: "mem_30",   icon: "📆", name: "One Month",              desc: "Be a member for 30 days",            category: "Member" },
  { id: "mem_180",  icon: "🗓️", name: "Half Year",              desc: "Be a member for 180 days",           category: "Member" },
  { id: "mem_365",  icon: "🎂", name: "Veteran",                desc: "Be a member for 1 year",             category: "Member" },
  { id: "mem_730",  icon: "🏛️", name: "Pillar of the Community",desc: "Be a member for 2 years",            category: "Member" },
  { id: "mem_1825", icon: "🌐", name: "Living Legend",          desc: "Be a member for 5 years",            category: "Member" },
  // — Seasonal / holiday (evaluated against the device-local calendar date at scan time)
  { id: "season_halloween",    icon: "🎃", name: "Trick-or-Treasure",   desc: "Scan 5 coins on Halloween (Oct 31)",        category: "Seasonal" },
  { id: "season_friday13",     icon: "🕷️", name: "Unlucky for Some",    desc: "Scan a coin on Friday the 13th",            category: "Seasonal" },
  { id: "season_christmas",    icon: "🎄", name: "Silver Bells",        desc: "Scan a coin on Christmas Day (Dec 25)",     category: "Seasonal" },
  { id: "season_newyear",      icon: "🎆", name: "New Year, New Coins", desc: "Scan 3 coins on New Year's Day (Jan 1)",    category: "Seasonal" },
  { id: "season_valentine",    icon: "💘", name: "Lucky in Love",       desc: "Scan a coin on Valentine's Day (Feb 14)",   category: "Seasonal" },
  { id: "season_stpatrick",    icon: "🍀", name: "Pot of Gold",         desc: "Scan a coin on St. Patrick's Day (Mar 17)", category: "Seasonal" },
  { id: "season_july4",        icon: "🎇", name: "Independence Stack",  desc: "Scan 4 coins on Independence Day (Jul 4)",  category: "Seasonal" },
  { id: "season_thanksgiving", icon: "🦃", name: "Turkey Day Treasure", desc: "Scan a coin on Thanksgiving",               category: "Seasonal" },
  // — Variety & streaks
  { id: "var_nickel_streak",   icon: "🪙", name: "Nickel Streak",       desc: "Scan 5 nickels in a row",                       category: "Variety" },
  { id: "var_penny_streak",    icon: "🅿️", name: "Penny Pincher",       desc: "Scan 5 pennies in a row",                       category: "Variety" },
  { id: "var_dime_streak",     icon: "🎙️", name: "Dime Dash",           desc: "Scan 5 dimes in a row",                         category: "Variety" },
  { id: "var_quarter_streak",  icon: "🦅", name: "Quarter Quartet",     desc: "Scan 4 quarters in a row",                      category: "Variety" },
  { id: "var_wheat_streak",    icon: "🌾", name: "Wheat Row",           desc: "Scan 3 wheat pennies in a row",                 category: "Variety" },
  { id: "var_on_a_roll",       icon: "🎯", name: "On a Roll",           desc: "Scan 5 of the same denomination in a row",      category: "Variety" },
  { id: "var_full_set",        icon: "🧺", name: "Full Set",            desc: "Scan a penny, nickel, dime, and quarter",       category: "Variety" },
  { id: "var_night_owl",       icon: "🌙", name: "Night Owl",           desc: "Scan a coin between midnight and 3 AM",         category: "Variety" },
  { id: "var_early_bird",      icon: "🌅", name: "Early Bird",          desc: "Scan a coin between 4 AM and 6 AM",             category: "Variety" },
  { id: "var_quickfire",       icon: "⚡", name: "Quickfire",           desc: "Scan two coins within 60 seconds of each other",category: "Variety" },
  { id: "var_old_soul",        icon: "🕰️", name: "Old Soul",            desc: "Scan a coin minted before 1950",                category: "Variety" },
  { id: "var_time_machine",    icon: "⏳", name: "Time Machine",        desc: "Scan coins spanning 100+ years apart",          category: "Variety" },
  // — Coin types
  { id: "type_penny",   icon: "🟤", name: "Copper Cent",   desc: "Scan a penny",                       category: "Coin Types" },
  { id: "type_nickel",  icon: "⚪", name: "Nickel Novice", desc: "Scan a nickel",                      category: "Coin Types" },
  { id: "type_dime",    icon: "🥈", name: "Perfect Ten",   desc: "Scan a dime",                        category: "Coin Types" },
  { id: "type_quarter", icon: "🦅", name: "Quarter Master",desc: "Scan a quarter",                     category: "Coin Types" },
  { id: "type_half",    icon: "🎖️", name: "Half Measures", desc: "Scan a half dollar",                 category: "Coin Types" },
  { id: "type_dollar",  icon: "💵", name: "Dollar Sign",   desc: "Scan a dollar coin",                 category: "Coin Types" },
  { id: "type_wheat",   icon: "🌾", name: "Wheat Field",   desc: "Scan a wheat penny",                 category: "Coin Types" },
  { id: "type_foreign", icon: "🌍", name: "World Traveler",desc: "Scan a coin from outside the U.S.",  category: "Coin Types" },
];

export const BADGE_CATEGORIES = ["Scanning", "Net Worth", "Member", "Seasonal", "Variety", "Coin Types"];
