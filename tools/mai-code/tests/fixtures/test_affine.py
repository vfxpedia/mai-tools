"""TEST ONLY oracle, fixed before any model writes affine.py."""
import math
import sys
import unittest
from affine import affine_loss
NEGATIVE='--negative' in sys.argv
if NEGATIVE:sys.argv.remove('--negative')


class AffineTests(unittest.TestCase):
    def test_known_gradients(self):
        y,loss,dw,db,dx=affine_loss([1,2],[3,4],1,10)
        if NEGATIVE:dw=[0,8]  # Known-bad candidate, never change the acceptance oracle.
        self.assertEqual((y,loss),(12,4))
        self.assertEqual(dw,[4,8]);self.assertEqual(db,4);self.assertEqual(dx,[12,16])

    def test_finite_difference(self):
        step=1e-6
        for i,want in enumerate([4,8]):
            up=[3.,4.];down=[3.,4.];up[i]+=step;down[i]-=step
            derivative=(affine_loss([1,2],up,1,10)[1]-affine_loss([1,2],down,1,10)[1])/(2*step)
            self.assertAlmostEqual(derivative,want,delta=1e-5)

    def test_invalid_shape(self):
        with self.assertRaises(ValueError):affine_loss([1],[3,4],1,10)

    def test_nonfinite(self):
        for value in (math.inf,math.nan):
            with self.assertRaises(ValueError):affine_loss([value,2],[3,4],1,10)

if __name__=='__main__':unittest.main(verbosity=2)
