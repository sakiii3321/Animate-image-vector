import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from methods import fit_gradient,remove_edge_mixtures,records_for,ridge_mask,residual_regions,join_thin_neighbors,centerline_paths

class MethodsTests(unittest.TestCase):
    def test_linear_gradient_improves_held_out_pixels(self):
        yy,xx=np.mgrid[:80,:120];points=np.column_stack((xx.ravel(),yy.ravel()))
        values=np.column_stack((40+xx.ravel(),80+.5*xx.ravel(),180-.5*xx.ravel()))
        fit=fit_gradient(points,values,values.mean(axis=0))
        self.assertIsNotNone(fit);self.assertLess(fit['validation_mse_after'],1)
        self.assertGreater(fit['validation_mse_before'],100)

    def test_random_texture_does_not_become_a_gradient(self):
        yy,xx=np.mgrid[:80,:120];points=np.column_stack((xx.ravel(),yy.ravel()))
        values=np.random.default_rng(42).integers(80,160,(len(points),3))
        self.assertIsNone(fit_gradient(points,values,values.mean(axis=0)))

    def test_edge_mix_absorbed_but_real_dot_preserved(self):
        labels=np.ones((40,80),np.uint16);labels[8:32,20:50]=2
        labels[10:18,50]=3;labels[5:7,65:67]=4
        colors=np.array([[0,0,0,0],[255,255,255,255],[100,0,0,255],[177,127,127,255],[0,0,0,255]],np.uint8)
        labels,records=records_for(labels,colors[labels])
        cleaned,items,removed=remove_edge_mixtures(labels,records)
        self.assertEqual(len(removed),1)
        self.assertEqual(cleaned[12,50],cleaned[12,49])
        self.assertNotEqual(cleaned[5,65],cleaned[0,0])
        self.assertEqual(len(items),3)

    def test_continuous_dark_stroke_produces_long_residual(self):
        rgba=np.full((100,160,4),255,np.uint8);rgba[48:52,10:150,:3]=40
        ridge=ridge_mask(rgba)
        self.assertGreater(ridge[49:51,12:148].mean(),.95)
        rendered=np.full_like(rgba,255)
        labels,records,_=residual_regions(rgba,rendered,ridge,20,line_pass=True)
        self.assertTrue(records)
        self.assertGreater((labels[49:51,12:148]>0).mean(),.95)
        self.assertLessEqual(len(records),2)

    def test_diagonal_ink_fragments_join_without_absorbing_background(self):
        labels=np.ones((40,40),np.uint16)
        for i in range(8,30):labels[i,i]=i-6
        colors=np.full((int(labels.max())+1,4),255,np.uint8);colors[2:,:3]=[40,8,22]
        labels,records=records_for(labels,colors[labels])
        joined,records,count=join_thin_neighbors(labels,records)
        self.assertEqual(len(records),2);self.assertGreater(count,15)
        self.assertNotEqual(joined[10,10],joined[10,11])
        self.assertEqual(joined[8,8],joined[29,29])

    def test_centerline_is_not_split_by_small_color_variations(self):
        source=np.full((100,160,4),255,np.uint8)
        for x in range(10,150):source[48:52,x,:3]=40+(x%3)*4
        current=np.full_like(source,255);mask=ridge_mask(source)
        group,guard,report=centerline_paths(source,current,mask,20)
        self.assertEqual(len(group),1)
        self.assertGreater(guard[49,14:146].mean(),.99)
        self.assertEqual(group[0].get('fill'),'none')

if __name__=='__main__':unittest.main(verbosity=2)
