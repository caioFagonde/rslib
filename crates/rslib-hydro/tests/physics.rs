use rslib_hydro::*;
use std::f64::consts::PI;

fn cell() -> Cell {
    Cell {
        slope_deg: 30.0,
        water_table_depth_m: 2.0,
        conductivity_m_s: 1e-5,
        diffusivity_m2_s: 1e-4,
        background_flux_m_s: 0.0,
        cohesion_pa: 1000.0,
        friction_deg: 35.0,
        unit_weight_n_m3: 19000.0,
        boundary: Boundary::Infinite,
        rain_multiplier: 1.0,
    }
}
fn problem() -> Problem {
    Problem {
        cells: vec![cell()],
        rain: vec![Rain {
            start_s: 0.0,
            end_s: 3600.0,
            intensity_m_s: 2e-6,
        }],
        depths_m: vec![0.5, 1.0, 2.0],
        times_s: vec![0.0, 1800.0, 3600.0, 7200.0],
        routing: None,
    }
}
fn close(a: f64, b: f64, tol: f64) {
    assert!((a - b).abs() <= tol, "{a} != {b}");
}

#[test]
fn special_function_independent_scipy_values() {
    for (x, expected) in [
        (0.0, 0.5641895835477563),
        (1.0, 0.050254541660012225),
        (4.0, 1.8221417582127117e-9),
        (8.0, 6.90962458935802e-31),
        (12.0, 5.612508902316381e-66),
    ] {
        close(ierfc(x) / expected, 1.0, 2e-11);
    }
}
#[test]
fn infinite_surface_closed_form_and_initial_limit() {
    close(
        step_response(0.0, 25.0, 4.0, &Boundary::Infinite).unwrap(),
        20.0 / PI.sqrt(),
        1e-12,
    );
    close(
        step_response(1.0, 0.0, 4.0, &Boundary::Infinite).unwrap(),
        0.0,
        0.0,
    );
    assert!(step_response(1.0, 1e-9, 1e-4, &Boundary::Infinite).unwrap() < 1e-100);
}
#[test]
fn finite_response_agrees_with_independent_image_sum_across_switch() {
    let l: f64 = 2.0;
    for tau in [0.001, 0.24999, 0.25001, 1.0, 10.0] {
        for z in [0.0, 0.1, 1.0, 2.0] {
            let root = (tau * l * l).sqrt();
            let mut expected = 0.0;
            for m in 1..1000 {
                let a = (2.0 * (m - 1) as f64 * l + z) / (2.0 * root);
                let b = (2.0 * m as f64 * l - z) / (2.0 * root);
                expected += ((-a * a).exp() / PI.sqrt() - a * libm::erfc(a))
                    + ((-b * b).exp() / PI.sqrt() - b * libm::erfc(b));
            }
            close(
                step_response(z, tau * l * l, 1.0, &Boundary::Finite { depth_m: l }).unwrap(),
                2.0 * root * expected,
                1e-10,
            );
        }
    }
}
#[test]
fn finite_column_conserves_integrated_pressure_response() {
    let l = 2.0;
    for t in [0.01, 1.0, 10.0] {
        let n = 4000;
        let dz = l / n as f64;
        let mut integral = 0.0;
        for k in 0..=n {
            let weight = if k == 0 || k == n {
                1.0
            } else if k % 2 == 0 {
                2.0
            } else {
                4.0
            };
            integral += weight
                * step_response(k as f64 * dz, t, 1.0, &Boundary::Finite { depth_m: l }).unwrap();
        }
        close(integral * dz / 3.0, t, 1e-9);
    }
}
#[test]
fn finite_deep_boundary_matches_infinite() {
    close(
        step_response(1.0, 1000.0, 1e-4, &Boundary::Finite { depth_m: 100.0 }).unwrap(),
        step_response(1.0, 1000.0, 1e-4, &Boundary::Infinite).unwrap(),
        1e-12,
    );
}
#[test]
fn pulse_splitting_preserves_solution_and_initial_state() {
    let p = problem();
    let a = simulate(&p).unwrap();
    let mut q = p.clone();
    q.rain = vec![
        Rain {
            start_s: 0.0,
            end_s: 1800.0,
            intensity_m_s: 2e-6,
        },
        Rain {
            start_s: 1800.0,
            end_s: 3600.0,
            intensity_m_s: 2e-6,
        },
    ];
    let b = simulate(&q).unwrap();
    for (x, y) in a.cells[0].samples.iter().zip(&b.cells[0].samples) {
        close(x.head_m, y.head_m, 1e-12);
    }
    close(a.cells[0].samples[0].head_m, (0.5 - 2.0) * 0.75, 1e-12);
}
#[test]
fn head_limit_is_enforced_and_rain_reduces_stability() {
    let mut p = problem();
    p.rain[0].end_s = 1e6;
    p.rain[0].intensity_m_s = 1e-5;
    p.times_s = vec![0.0, 1e6];
    let r = simulate(&p).unwrap();
    assert!(r.cells[0].samples.iter().any(|s| s.head_capped));
    for s in &r.cells[0].samples {
        assert!(s.head_m <= s.depth_m * 0.75 + 1e-12);
    }
    assert!(r.cells[0].samples[3].factor_of_safety < r.cells[0].samples[0].factor_of_safety);
}
#[test]
fn downhill_routing_infiltrates_runon_and_balances_mass() {
    let mut p = problem();
    p.cells = vec![cell(); 3];
    p.cells[0].conductivity_m_s = 1e-6;
    p.cells[1].conductivity_m_s = 2e-5;
    p.cells[2].conductivity_m_s = 1e-6;
    p.rain[0].intensity_m_s = 1e-5;
    p.routing = Some(RoutingGrid {
        width: 3,
        height: 1,
        cell_size_m: 10.0,
        elevations_m: vec![3.0, 2.0, 1.0],
    });
    let r = simulate(&p).unwrap();
    let w = &r.water_balance[0];
    close(w.input_m3, 10.8, 1e-12);
    close(w.infiltrated_m3, 7.56, 1e-12);
    close(w.exported_excess_m3, 3.24, 1e-12);
    close(w.residual_m3, 0.0, 1e-12);
}
#[test]
fn rejects_invalid_or_unsupported_conditions() {
    let mut p = problem();
    p.cells[0].background_flux_m_s = 1e-4;
    assert!(simulate(&p).is_err());
    let mut p = problem();
    p.cells[0].slope_deg = 0.0;
    assert!(simulate(&p).is_err());
    let mut p = problem();
    p.rain.push(p.rain[0].clone());
    assert!(simulate(&p).is_err());
    assert!(step_response(3.0, 1.0, 1.0, &Boundary::Finite { depth_m: 2.0 }).is_err());
}
