//! Independent Rust implementation of wet-initial-condition equations in USGS
//! OFR 2008-1159, equations 1A, 1B, 2, 3A and the infinite-slope stress balance.
//! Source: https://pubs.usgs.gov/of/2008/1159/ . No legacy code or executable.
//! Unsaturated Gardner/Richards coupling is not yet implemented.

use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::f64::consts::PI;

pub type Result<T> = std::result::Result<T, String>;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Boundary {
    Infinite,
    Finite { depth_m: f64 },
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Cell {
    pub slope_deg: f64,
    pub water_table_depth_m: f64,
    pub conductivity_m_s: f64,
    pub diffusivity_m2_s: f64,
    pub background_flux_m_s: f64,
    pub cohesion_pa: f64,
    pub friction_deg: f64,
    pub unit_weight_n_m3: f64,
    pub boundary: Boundary,
    #[serde(default = "one")]
    pub rain_multiplier: f64,
}

fn one() -> f64 {
    1.0
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Rain {
    pub start_s: f64,
    pub end_s: f64,
    pub intensity_m_s: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RoutingGrid {
    pub width: usize,
    pub height: usize,
    pub cell_size_m: f64,
    pub elevations_m: Vec<f64>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Problem {
    pub cells: Vec<Cell>,
    pub rain: Vec<Rain>,
    pub depths_m: Vec<f64>,
    pub times_s: Vec<f64>,
    #[serde(default)]
    pub routing: Option<RoutingGrid>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Sample {
    pub time_s: f64,
    pub depth_m: f64,
    pub raw_head_m: f64,
    pub head_m: f64,
    pub head_capped: bool,
    pub factor_of_safety: f64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CellResult {
    pub cell: usize,
    pub minimum_factor_of_safety: f64,
    pub critical_depth_m: f64,
    pub critical_time_s: f64,
    pub samples: Vec<Sample>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct WaterBalance {
    pub start_s: f64,
    pub end_s: f64,
    pub input_m3: f64,
    pub infiltrated_m3: f64,
    pub exported_excess_m3: f64,
    pub residual_m3: f64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Simulation {
    pub schema_version: String,
    pub implementation: String,
    pub reference: String,
    pub limitations: Vec<String>,
    pub water_balance: Vec<WaterBalance>,
    pub cells: Vec<CellResult>,
}

/// Integral of erfc(x), x >= 0. Asymptotic expansion avoids tail cancellation.
pub fn ierfc(x: f64) -> f64 {
    if x < 8.0 {
        ((-x * x).exp() / PI.sqrt() - x * libm::erfc(x)).max(0.0)
    } else {
        let q = 1.0 / (2.0 * x * x);
        let mut term = q;
        let mut sum = term;
        for n in 1..16 {
            term *= -((2 * n + 1) as f64) * q;
            sum += term;
            if term.abs() < sum.abs() * 1e-16 {
                break;
            }
        }
        (-x * x).exp() / PI.sqrt() * sum
    }
}

/// Unit flux/Ks response with units of length; USGS equations 1A/2.
/// D1 = D0 / cos²(slope), supplied by the caller of this primitive.
pub fn step_response(z: f64, elapsed_s: f64, d1: f64, boundary: &Boundary) -> Result<f64> {
    if ![z, elapsed_s, d1].iter().all(|v| v.is_finite()) || z < 0.0 || d1 <= 0.0 {
        return Err("Step response requires finite z >= 0, time, and D1 > 0".into());
    }
    if let Boundary::Finite { depth_m: l } = boundary {
        if !l.is_finite() || *l <= 0.0 || z > *l {
            return Err("Finite boundary must be positive and at or below evaluation depth".into());
        }
    }
    if elapsed_s <= 0.0 {
        return Ok(0.0);
    }
    let dt = d1 * elapsed_s;
    if !dt.is_finite() {
        return Err("Diffusion time overflow".into());
    }
    let root = dt.sqrt();
    match boundary {
        Boundary::Infinite => Ok(2.0 * root * ierfc(z / (2.0 * root))),
        Boundary::Finite { depth_m: l } => {
            let tau = dt / (l * l);
            if tau > 0.25 {
                // Equivalent Neumann heat-equation eigenfunction expansion at late time.
                let mut sum = 0.0;
                for n in 1..10000 {
                    let nf = n as f64;
                    let envelope = (-nf * nf * PI * PI * tau).exp() / (nf * nf);
                    sum += (nf * PI * z / l).cos() * envelope;
                    if envelope < 1e-14 {
                        return Ok((dt / l + l / 3.0 - z + z * z / (2.0 * l)
                            - 2.0 * l / PI.powi(2) * sum)
                            .max(0.0));
                    }
                }
                Err("Finite eigenfunction series failed to converge".into())
            } else {
                let mut sum = 0.0;
                for m in 1..10000 {
                    let a = 2.0 * ((m - 1) as f64) * l + z;
                    let b = 2.0 * (m as f64) * l - z;
                    let term = ierfc(a / (2.0 * root)) + ierfc(b / (2.0 * root));
                    sum += term;
                    if term < 1e-14 + sum * 1e-12 {
                        return Ok(2.0 * root * sum);
                    }
                }
                Err("Finite image series failed to converge".into())
            }
        }
    }
}

pub fn validate(p: &Problem) -> Result<()> {
    if p.cells.is_empty()
        || p.cells.len() > 1_000_000
        || p.times_s.is_empty()
        || p.depths_m.is_empty()
    {
        return Err("Need cells, depths and output times; maximum one million cells".into());
    }
    if p.cells
        .len()
        .saturating_mul(p.times_s.len())
        .saturating_mul(p.depths_m.len())
        > 2_000_000
        || p.rain.len() > 10000
    {
        return Err("Output/forcing budget exceeded; split the domain or time windows".into());
    }
    let forcing_count = p.cells.len().saturating_mul(p.rain.len());
    let operation_count = forcing_count
        .saturating_mul(p.times_s.len())
        .saturating_mul(p.depths_m.len());
    if forcing_count > 8_000_000 || operation_count > 200_000_000 {
        return Err("Forcing-memory or computation budget exceeded; split the problem".into());
    }
    for seq in [&p.times_s, &p.depths_m] {
        if seq.iter().any(|x| !x.is_finite()) || seq.windows(2).any(|x| x[0] >= x[1]) {
            return Err("Depths and times must be finite, strictly increasing".into());
        }
    }
    if p.times_s[0] < 0.0 || p.depths_m[0] <= 0.0 {
        return Err("Times must be nonnegative and depths positive".into());
    }
    let mut previous_end = 0.0;
    for rain in &p.rain {
        if ![rain.start_s, rain.end_s, rain.intensity_m_s]
            .iter()
            .all(|v| v.is_finite())
            || rain.start_s < previous_end
            || rain.end_s <= rain.start_s
            || rain.intensity_m_s < 0.0
        {
            return Err("Rain intervals must be ordered, nonoverlapping, positive duration and nonnegative intensity".into());
        }
        previous_end = rain.end_s;
    }
    for (i, c) in p.cells.iter().enumerate() {
        if ![
            c.slope_deg,
            c.water_table_depth_m,
            c.conductivity_m_s,
            c.diffusivity_m2_s,
            c.background_flux_m_s,
            c.cohesion_pa,
            c.friction_deg,
            c.unit_weight_n_m3,
            c.rain_multiplier,
        ]
        .iter()
        .all(|v| v.is_finite())
            || c.slope_deg <= 0.0
            || c.slope_deg >= 89.0
            || c.water_table_depth_m < 0.0
            || c.conductivity_m_s <= 0.0
            || c.diffusivity_m2_s <= 0.0
            || c.background_flux_m_s < 0.0
            || c.cohesion_pa < 0.0
            || c.friction_deg < 0.0
            || c.friction_deg >= 90.0
            || c.unit_weight_n_m3 <= 0.0
            || c.rain_multiplier < 0.0
        {
            return Err(format!("Invalid material/initial condition at cell {i}"));
        }
        let beta =
            c.slope_deg.to_radians().cos().powi(2) - c.background_flux_m_s / c.conductivity_m_s;
        if beta < 0.0 {
            return Err(format!(
                "Upward initial gradients are unsupported at cell {i}"
            ));
        }
        step_response(*p.depths_m.last().unwrap(), 0.0, 1.0, &c.boundary)?;
        if let Boundary::Finite { depth_m } = c.boundary {
            if c.water_table_depth_m > depth_m {
                return Err("Water table cannot be below a finite basal boundary".into());
            }
        }
    }
    if let Some(g) = &p.routing {
        if g.width == 0
            || g.height == 0
            || g.width.saturating_mul(g.height) != p.cells.len()
            || g.elevations_m.len() != p.cells.len()
            || !g.cell_size_m.is_finite()
            || g.cell_size_m <= 0.0
            || g.elevations_m.iter().any(|z| !z.is_finite())
        {
            return Err("Routing requires a finite metric square-cell DEM matching cells in row-major order".into());
        }
    }
    Ok(())
}

/// Steepest strictly-downhill D8 routing. No travel-time/storage or flat/depression filling.
fn receivers(g: &RoutingGrid) -> Vec<Option<usize>> {
    (0..g.elevations_m.len())
        .map(|i| {
            let row = (i / g.width) as isize;
            let col = (i % g.width) as isize;
            let mut best = None;
            let mut steepest = 0.0;
            for dr in -1isize..=1 {
                for dc in -1isize..=1 {
                    let (r, c) = (row + dr, col + dc);
                    if (dr == 0 && dc == 0)
                        || r < 0
                        || c < 0
                        || r >= g.height as isize
                        || c >= g.width as isize
                    {
                        continue;
                    }
                    let j = r as usize * g.width + c as usize;
                    let slope = (g.elevations_m[i] - g.elevations_m[j])
                        / ((dr * dr + dc * dc) as f64).sqrt();
                    if slope > steepest {
                        steepest = slope;
                        best = Some(j);
                    }
                }
            }
            best
        })
        .collect()
}

fn forcing(p: &Problem) -> (Vec<Vec<Rain>>, Vec<WaterBalance>) {
    let mut by_cell = vec![Vec::new(); p.cells.len()];
    let mut balance = Vec::new();
    let area = p
        .routing
        .as_ref()
        .map(|g| g.cell_size_m.powi(2))
        .unwrap_or(1.0);
    let downstream = p.routing.as_ref().map(receivers);
    let mut order: Vec<usize> = (0..p.cells.len()).collect();
    if let Some(g) = &p.routing {
        order.sort_by(|a, b| g.elevations_m[*b].total_cmp(&g.elevations_m[*a]));
    }
    for rain in &p.rain {
        let mut supply: Vec<f64> = p
            .cells
            .iter()
            .map(|c| rain.intensity_m_s * c.rain_multiplier * area)
            .collect();
        let total: f64 = supply.iter().sum();
        let (mut infiltrated, mut exported) = (0.0, 0.0);
        for &i in &order {
            let flux = supply[i].min(p.cells[i].conductivity_m_s * area);
            let excess = supply[i] - flux;
            infiltrated += flux;
            by_cell[i].push(Rain {
                start_s: rain.start_s,
                end_s: rain.end_s,
                intensity_m_s: flux / area,
            });
            if let Some(j) = downstream.as_ref().and_then(|d| d[i]) {
                supply[j] += excess;
            } else {
                exported += excess;
            }
        }
        let duration = rain.end_s - rain.start_s;
        balance.push(WaterBalance {
            start_s: rain.start_s,
            end_s: rain.end_s,
            input_m3: total * duration,
            infiltrated_m3: infiltrated * duration,
            exported_excess_m3: exported * duration,
            residual_m3: (total - infiltrated - exported) * duration,
        });
    }
    (by_cell, balance)
}

fn solve_cell(i: usize, c: &Cell, rain: &[Rain], p: &Problem) -> Result<CellResult> {
    let beta = c.slope_deg.to_radians().cos().powi(2) - c.background_flux_m_s / c.conductivity_m_s;
    let d1 = c.diffusivity_m2_s / c.slope_deg.to_radians().cos().powi(2);
    let mut samples = Vec::with_capacity(p.times_s.len() * p.depths_m.len());
    for &t in &p.times_s {
        for &z in &p.depths_m {
            let mut head = (z - c.water_table_depth_m) * beta;
            for r in rain {
                if t <= r.start_s {
                    break;
                }
                head += r.intensity_m_s / c.conductivity_m_s
                    * (step_response(z, t - r.start_s, d1, &c.boundary)?
                        - step_response(z, t - r.end_s, d1, &c.boundary)?);
            }
            let capped = head.min(z * beta);
            let slope = c.slope_deg.to_radians();
            let friction = c.friction_deg.to_radians().tan();
            let fs = friction / slope.tan()
                + (c.cohesion_pa - capped * 9810.0 * friction)
                    / (c.unit_weight_n_m3 * z * slope.sin() * slope.cos());
            if !head.is_finite() || !fs.is_finite() {
                return Err(format!("Numerical overflow at cell {i}"));
            }
            samples.push(Sample {
                time_s: t,
                depth_m: z,
                raw_head_m: head,
                head_m: capped,
                head_capped: head > capped,
                factor_of_safety: fs,
            });
        }
    }
    let critical = samples
        .iter()
        .min_by(|a, b| a.factor_of_safety.total_cmp(&b.factor_of_safety))
        .unwrap();
    Ok(CellResult {
        cell: i,
        minimum_factor_of_safety: critical.factor_of_safety,
        critical_depth_m: critical.depth_m,
        critical_time_s: critical.time_s,
        samples,
    })
}

pub fn simulate(p: &Problem) -> Result<Simulation> {
    validate(p)?;
    let (rain, water_balance) = forcing(p);
    let cells: Result<Vec<_>> = p
        .cells
        .par_iter()
        .enumerate()
        .map(|(i, c)| solve_cell(i, c, &rain[i], p))
        .collect();
    Ok(Simulation {schema_version:"rslib-hydro/1".into(),implementation:env!("CARGO_PKG_VERSION").into(),
        reference:"USGS OFR 2008-1159 equations 1A/1B/2/3A and infinite-slope stress balance".into(),
        limitations:vec!["Wet/tension-saturated, homogeneous isotropic columns only; unsaturated coupling and upward initial flow are unsupported".into(),
            "D8 uses instantaneous strictly-downhill transfer; terminal excess includes pits/outlets; no storage, flat resolution or travel time".into(),
            "Without routing, water-balance volumes assume independent 1 m2 columns".into(),
            "Minimum FS is sampled at requested depths/times; no continuous minimum search or USGS legacy parity certification".into()],water_balance,cells:cells?})
}
