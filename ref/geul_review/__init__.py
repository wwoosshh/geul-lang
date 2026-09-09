"""Executable review-language core, separate from the stable .gl compiler."""

from .core import Program, Rule, ReviewError, parse, render, evaluate, differences

__all__ = ['Program', 'Rule', 'ReviewError', 'parse', 'render', 'evaluate', 'differences']
