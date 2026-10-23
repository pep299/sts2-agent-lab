//! 公開スナップショットを逐次復元して探索する方策用のPython拡張。
//! 別の状態生成APIや、同一プロセスの並列復元は差し替えの対象外。

use pyo3::prelude::*;
use pyo3::types::PyModule;
use sts2_core::{card_effects, cards::CardId};

mod wish;

#[pyfunction(pass_module)]
fn state_from_dict<'py>(
    module: &Bound<'py, PyModule>,
    data: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let state = module.getattr("_upstream_state_from_dict")?.call1((data,));
    // 上流の状態復元は標準ハンドラーを再登録するため、その後に上書きする。
    card_effects::register(CardId::Wish, wish::play);
    state
}

#[pymodule]
fn mentor_rs(module: &Bound<'_, PyModule>) -> PyResult<()> {
    sts2_rs::sts2_rs(module)?;
    module.add("_upstream_state_from_dict", module.getattr("state_from_dict")?)?;
    module.add_function(wrap_pyfunction!(state_from_dict, module)?)?;
    Ok(())
}
